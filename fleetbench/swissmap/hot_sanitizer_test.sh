# Copyright 2022 The Fleetbench Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# This file defines the skeleton of generated benchmark files. It contains
# the includes, gunit benchmark code, and main entrypoint.

#!/bin/bash

set -ex

"${TEST_SRCDIR}/com_google_fleetbench/fleetbench/swissmap/hot_swissmap_benchmark" --benchmark_filter="BM_.*::absl::flat_hash_set.*64.*set_size:64.*density:0"

echo "PASS"
