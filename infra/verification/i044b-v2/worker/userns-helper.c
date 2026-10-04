/* Fixed namespace/SCM_RIGHTS primitive; no command, environment or path API.
 * AppArmor's capability rule is a permission ceiling, never a capability grant.
 * Reject initial-namespace capabilities and root before creating any namespace.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/capability.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static int channel = -1;
static const char *stage = "precondition";

static void fail(void) {
    int error = errno ? errno : EPERM;
    char message[96];
    int size = snprintf(message, sizeof message, "E:%s:%d", stage, error);
    if (channel >= 0) (void)send(channel, message, (size_t)size, MSG_NOSIGNAL);
    _exit(1);
}

static void write_fixed(const char *path, const char *value) {
    int fd = open(path, O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) fail();
    size_t size = strlen(value);
    if (write(fd, value, size) != (ssize_t)size) fail();
    if (close(fd)) fail();
}

static void anchor_denied(void) {
    int fd = open("/run/novalton-verification-proc/full/self/status", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) { close(fd); errno = EPERM; fail(); }
    if (errno != EACCES) fail();
}

int main(int argc, char **argv) {
    char *end;
    if (argc != 3) return 2;
    long descriptor = strtol(argv[1], &end, 10);
    if (*end || descriptor < 3 || descriptor > 65535) return 2;
    channel = (int)descriptor;
    /* Only an inherited seqpacket from our same-UID direct parent is admitted. */
    struct ucred peer;
    socklen_t size = sizeof peer;
    int type;
    socklen_t type_size = sizeof type;
    uid_t uid = getuid();
    gid_t gid = getgid();
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct caps[2] = {{0}};
    if (!uid || !gid || getuid() != geteuid() || getgid() != getegid()
        || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1
        || syscall(SYS_capget, &header, caps)
        || caps[0].effective || caps[1].effective || caps[0].permitted
        || caps[1].permitted || caps[0].inheritable || caps[1].inheritable
        || getsockopt(channel, SOL_SOCKET, SO_TYPE, &type, &type_size)
        || type != SOCK_SEQPACKET
        || getsockopt(channel, SOL_SOCKET, SO_PEERCRED, &peer, &size)
        || size != sizeof peer || peer.uid != uid || peer.pid != getppid()) fail();
    FILE *profile_stream = fopen("/proc/self/attr/current", "re");
    char profile[128];
    if (!profile_stream || !fgets(profile, sizeof profile, profile_stream)
        || fclose(profile_stream) || strcmp(profile, "novalton-i044b-userns (enforce)\n")) fail();
    stage = "anchor_as_host";
    anchor_denied();
    /* LSM allows this operation, kernel initial-namespace capabilities do not.
     * A successful host mount operation is a hard failure, never accepted. */
    errno = 0;
    if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) != -1 || errno != EPERM) fail();
    /* Run membership is derived from the supervisor, never a caller path. */
    if (strlen(argv[2]) != 32 || strspn(argv[2], "0123456789abcdef") != 32) fail();
    FILE *stream = fopen("/proc/self/cgroup", "re");
    char current[4096], group[4200];
    if (!stream || !fgets(current, sizeof current, stream) || fclose(stream)) fail();
    size_t length = strlen(current);
    if (length < 15 || strcmp(current + length - 12, "/supervisor\n") || strncmp(current, "0::/", 4)) fail();
    current[length - 12] = '\0';
    if (strstr(current, "..")) fail();
    snprintf(group, sizeof group, "/sys/fs/cgroup%s/run-%s/cgroup.procs", current + 3, argv[2]);
    char mapping[64];
    snprintf(mapping, sizeof mapping, "%d", getpid());
    write_fixed(group, mapping);
    stage = "unshare";
    if (unshare(CLONE_NEWUSER)) fail();
    stage = "uid_map";
    snprintf(mapping, sizeof mapping, "0 %u 1\n", uid);
    write_fixed("/proc/self/uid_map", mapping);
    stage = "gid_map";
    write_fixed("/proc/self/setgroups", "deny");
    snprintf(mapping, sizeof mapping, "0 %u 1\n", gid);
    write_fixed("/proc/self/gid_map", mapping);
    /* Fresh proc in a child PID+mount namespace: ProtectKernelTunables keeps
     * host proc/sys read-only. Only the new user namespace's limit is changed. */
    stage = "namespaced_caps";
    if (syscall(SYS_capget, &header, caps) || !(caps[0].effective & (1U << CAP_SYS_ADMIN))) fail();
    stage = "anchor_as_namespace";
    anchor_denied();
    stage = "private_unshare";
    if (unshare(CLONE_NEWNS | CLONE_NEWPID)) fail();
    stage = "private_fork";
    pid_t child = fork();
    if (child < 0) fail();
    if (child) {
        close(channel);
        int status;
        if (waitpid(child, &status, 0) != child) return 1;
        return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
    }
    stage = "private_mount";
    if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL)) fail();
    stage = "private_proc";
    if (mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL)) fail();
    stage = "namespace_limit";
    write_fixed("/proc/sys/user/max_user_namespaces", "0\n");
    stage = "namespace_open";
    if (prctl(PR_SET_DUMPABLE, 1, 0, 0, 0)) fail();
    int fd = open("/proc/self/ns/user", O_RDONLY | O_CLOEXEC);
    if (fd < 0) fail();
    char ready = 'R';
    struct iovec vector = {&ready, 1};
    char control[CMSG_SPACE(sizeof(int))] = {0};
    struct msghdr message = {0};
    message.msg_iov = &vector;
    message.msg_iovlen = 1;
    message.msg_control = control;
    message.msg_controllen = sizeof control;
    struct cmsghdr *ancillary = CMSG_FIRSTHDR(&message);
    ancillary->cmsg_level = SOL_SOCKET;
    ancillary->cmsg_type = SCM_RIGHTS;
    ancillary->cmsg_len = CMSG_LEN(sizeof fd);
    memcpy(CMSG_DATA(ancillary), &fd, sizeof fd);
    if (sendmsg(channel, &message, MSG_NOSIGNAL) != 1) fail();
    close(fd);
    (void)recv(channel, &ready, 1, 0);
    close(channel);
    return 0;
}
