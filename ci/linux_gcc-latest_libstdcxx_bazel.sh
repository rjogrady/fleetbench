#!/bin/bash
#
# Copyright 2022 The Fleetbench Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script that can be invoked to test fleetbench in a hermetic environment
# using a Docker image on Linux. You must have Docker installed to use this
# script.

set -euox pipefail

if [ -z ${FLEETBENCH_ROOT:-} ]; then
  FLEETBENCH_ROOT="$(realpath $(dirname ${0})/..)"
fi

if [ -z ${STD:-} ]; then
  STD="c++17"
fi

if [ -z ${BUILD_CONFIG:-} ]; then
  BUILD_CONFIG=("" "--config=opt")
fi

if [ -z ${EXCEPTIONS_MODE:-} ]; then
  EXCEPTIONS_MODE="-fno-exceptions -fexceptions"
fi

readonly DOCKER_CONTAINER="gcr.io/google.com/absl-177019/linux_hybrid-latest:20230217"

# USE_BAZEL_CACHE=1 only works on Kokoro.
# Without access to the credentials this won't work.
if [[ ${USE_BAZEL_CACHE:-0} -ne 0 ]]; then
  DOCKER_EXTRA_ARGS="--volume=${KOKORO_KEYSTORE_DIR}:/keystore:ro ${DOCKER_EXTRA_ARGS:-}"
  # Bazel doesn't track changes to tools outside of the workspace
  # (e.g. /usr/bin/gcc), so by appending the docker container to the
  # remote_http_cache url, we make changes to the container part of
  # the cache key. Hashing the key is to make it shorter and url-safe.
  container_key=$(echo ${DOCKER_CONTAINER} | sha256sum | head -c 16)
  BAZEL_EXTRA_ARGS="--remote_http_cache=https://storage.googleapis.com/absl-bazel-remote-cache/${container_key} --google_credentials=/keystore/73103_absl-bazel-remote-cache ${BAZEL_EXTRA_ARGS:-}"
fi

# Create and start the docker container.
docker run --name fleetbench --volume="${FLEETBENCH_ROOT}:/fleetbench:ro" \
        --workdir=/fleetbench \
        --cap-add=SYS_PTRACE \
        --detach=true \
        --interactive=true \
        --tty=true \
        --rm \
        ${DOCKER_EXTRA_ARGS:-} \
        ${DOCKER_CONTAINER} \
        /bin/bash

stop_docker() {
  docker stop fleetbench
}
trap stop_docker EXIT

# Install additional dependencies
docker exec fleetbench apt-get update
docker exec fleetbench apt-get install pip python3-numpy -y
docker exec fleetbench pip install zstandard
docker exec fleetbench pip install python-snappy
docker exec fleetbench pip install brotli

# Sanity check our setup
docker exec fleetbench /usr/local/bin/bazel test fleetbench:distro_test

for std in ${STD}; do
  for build_config in "${BUILD_CONFIG[@]}"; do
    for exceptions_mode in ${EXCEPTIONS_MODE}; do
      echo "--------------------------------------------------------------------"
      time docker exec \
        -e CC="/usr/local/bin/gcc" \
        -e BAZEL_CXXOPTS="-std=${std}" \
        fleetbench \
        /usr/local/bin/bazel test ... \
          ${build_config} \
          --copt="${exceptions_mode}" \
          --define="absl=1" \
          --distdir="/bazel-distdir" \
          --keep_going \
          --show_timestamps \
          --test_env="GTEST_INSTALL_FAILURE_SIGNAL_HANDLER=1" \
          --test_output=errors \
          --test_tag_filters=-benchmark \
          --test_size_filters=-enormous \
          ${BAZEL_EXTRA_ARGS:-}
    done
  done
done
