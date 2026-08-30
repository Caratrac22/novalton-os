#!/bin/sh
# Start one command in a clean, explicitly selected Novalton profile.
set -eu

if [ "$#" -lt 3 ] || [ "$2" != "--" ]; then
    echo "Usage: scripts/with-profile.sh {development|test} -- command [args...]" >&2
    exit 2
fi

profile="$1"
shift 2
case "$profile" in
    development) profile_file=".env" ;;
    test) profile_file=".env.test" ;;
    *) echo "ENVIRONMENT_BLOCKED: unsupported environment profile." >&2; exit 1 ;;
esac

if [ ! -f "$profile_file" ]; then
    echo "ENVIRONMENT_BLOCKED: required profile file $profile_file is missing." >&2
    exit 1
fi

# These are the complete profile-sensitive settings. Unset them only in this child process,
# then source exactly one selected profile so stale parent exports cannot win.
unset NOVALTON_ENV DATABASE_URL NOVALTON_TEST_DATABASE_URL POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_PORT \
    NOVALTON_LOG_LEVEL REDIS_URL REDIS_PORT QDRANT_URL QDRANT_HTTP_PORT QDRANT_GRPC_PORT \
    NOVALTON_API_BASE_URL NOVALTON_TENANT_ID NOVALTON_WORKSPACE_ID \
    NOVALTON_OPENAI_COMPATIBLE_BASE_URL NOVALTON_OPENAI_COMPATIBLE_API_KEY \
    NOVALTON_OPENAI_COMPATIBLE_PROVIDER_ID NOVALTON_OPENAI_COMPATIBLE_REQUIRE_PARAMETERS \
    NOVALTON_OPENAI_COMPATIBLE_RESPONSE_HEALING NOVALTON_OPENROUTER_CATALOG_ENABLED \
    NOVALTON_GOVERNED_PROVIDER_QUALIFICATIONS NOVALTON_MODEL_CATALOG_FREE_ALLOWLIST \
    NOVALTON_MODEL_ROUTER_FORCE_MODEL NOVALTON_PROVIDER_CONNECT_TIMEOUT_SECONDS \
    NOVALTON_PROVIDER_READ_TIMEOUT_SECONDS NOVALTON_PROVIDER_WRITE_TIMEOUT_SECONDS \
    NOVALTON_PROVIDER_POOL_TIMEOUT_SECONDS NOVALTON_PROVIDER_MAX_RESPONSE_BYTES \
    NOVALTON_MODEL_OUTPUT_TOKEN_SAFETY_CEILING NOVALTON_BOOTSTRAP_TENANT_ID \
    NOVALTON_BOOTSTRAP_TENANT_NAME NOVALTON_BOOTSTRAP_TENANT_SLUG NOVALTON_BOOTSTRAP_WORKSPACE_ID \
    NOVALTON_BOOTSTRAP_WORKSPACE_NAME NOVALTON_BOOTSTRAP_WORKSPACE_SLUG

set -a
. "./$profile_file"
set +a

if [ "${NOVALTON_ENV:-}" != "$profile" ]; then
    echo "ENVIRONMENT_BLOCKED: profile marker does not match selected profile." >&2
    exit 1
fi

if [ -z "${NOVALTON_PROFILE_VALIDATOR:-}" ]; then
    echo "ENVIRONMENT_BLOCKED: profile validator is not configured." >&2
    exit 1
fi
"$NOVALTON_PROFILE_VALIDATOR" -m novalton_api.core.environment validate >/dev/null
if [ "${NOVALTON_PROFILE_REQUIRE_DB_IDENTITY:-0}" = "1" ]; then
    "$NOVALTON_PROFILE_VALIDATOR" -m novalton_api.core.environment db-check >/dev/null
fi
exec "$@"
