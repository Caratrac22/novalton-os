/* Fixed AppArmor entry: never attach namespace permission to an ELF loader.
 * Only the exact system service run may execute the reviewed I-044A argv.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/capability.h>
#include <linux/close_range.h>
#include <linux/magic.h>
#include <linux/nsfs.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <unistd.h>

#define A "/opt/novalton-verification/i044a-v2"
#define B "/opt/novalton-verification/i044b-v2"

static void reject(void) { _exit(2); }

static void initial_mapping(const char *path) {
    FILE *stream = fopen(path, "re");
    unsigned long long inside, outside, count;
    char extra;
    if (!stream) reject();
    int fields = fscanf(stream, "%llu %llu %llu %c", &inside, &outside, &count, &extra);
    if (fclose(stream) || fields != 3 || inside || outside || count != 4294967295ULL) reject();
}

int main(int argc, char **argv) {
    if (argc != 3 || strlen(argv[2]) != 32 || strspn(argv[2], "0123456789abcdef") != 32) reject();
    char *end;
    long descriptor = strtol(argv[1], &end, 10);
    if (*end || descriptor < 3 || descriptor > 65535) reject();
    uid_t uid = getuid();
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct caps[2] = {{0}};
    if (!uid || !getgid() || uid != geteuid() || getgid() != getegid()
        || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1
        || syscall(SYS_capget, &header, caps)
        || caps[0].effective || caps[1].effective || caps[0].permitted
        || caps[1].permitted || caps[0].inheritable || caps[1].inheritable) reject();
    initial_mapping("/proc/self/uid_map");
    initial_mapping("/proc/self/gid_map");
    FILE *stream = fopen("/proc/self/attr/current", "re");
    char current[4096], expected[256];
    if (!stream || !fgets(current, sizeof current, stream) || fclose(stream)
        || strcmp(current, "novalton-i044a-bwrap (enforce)\n")) reject();
    snprintf(expected, sizeof expected,
        "0::/system.slice/novalton-verification.service/run-%s\n", argv[2]);
    stream = fopen("/proc/self/cgroup", "re");
    if (!stream || !fgets(current, sizeof current, stream) || fclose(stream)
        || strcmp(current, expected)) reject();
    struct statfs filesystem;
    uid_t owner;
    if (fstatfs((int)descriptor, &filesystem) || filesystem.f_type != NSFS_MAGIC
        || ioctl((int)descriptor, NS_GET_NSTYPE) != CLONE_NEWUSER
        || ioctl((int)descriptor, NS_GET_OWNER_UID, &owner) || owner != uid) reject();
    struct stat provided, own;
    if (fstat((int)descriptor, &provided) || stat("/proc/self/ns/user", &own)
        || (provided.st_dev == own.st_dev && provided.st_ino == own.st_ino)) reject();
    char namespace_fd[16], filter_fd[16], snapshot[256];
    snprintf(namespace_fd, sizeof namespace_fd, "%ld", descriptor);
    snprintf(snapshot, sizeof snapshot, "/var/lib/novalton-verification/snapshot-%s", argv[2]);
    int seccomp = open(A "/seccomp.bpf", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (seccomp < 3 || syscall(SYS_close_range, 3U, ~0U, CLOSE_RANGE_CLOEXEC)
        || fcntl((int)descriptor, F_SETFD, 0) || fcntl(seccomp, F_SETFD, 0)) reject();
    snprintf(filter_fd, sizeof filter_fd, "%d", seccomp);
    char *const arguments[] = {
        B "/bwrap-loader", "--inhibit-cache", "--library-path",
        A "/rootfs/usr/lib/x86_64-linux-gnu", A "/bwrap",
        "--userns", namespace_fd, "--sync-fd", namespace_fd,
        "--assert-userns-disabled", "--unshare-ipc", "--unshare-pid",
        "--unshare-net", "--unshare-uts", "--unshare-cgroup-try",
        "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
        "--ro-bind", A "/rootfs", "/", "--ro-bind", snapshot, "/source",
        "--proc", "/proc", "--dev", "/dev", "--size", "268435456",
        "--tmpfs", "/scratch", "--seccomp", filter_fd, "--chdir", "/scratch",
        "/runtime/bin/python3.13", "-I", "-S", "-B", "/runtime/i044a_probe.py", NULL,
    };
    char *const environment[] = {NULL};
    execve(B "/bwrap-loader", arguments, environment);
    reject();
}
