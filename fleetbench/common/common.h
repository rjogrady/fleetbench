// Copyright 2022 The Fleetbench Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
#ifndef THIRD_PARTY_FLEETBENCH_COMMON_COMMON_H_
#define THIRD_PARTY_FLEETBENCH_COMMON_COMMON_H_

#include <filesystem>  // NOLINT
#include <random>
#include <string>
#include <vector>

#include "absl/strings/string_view.h"

namespace fleetbench {

// Wrapper around a random number generator.
// If --fixed_seed is true (the default), the seed will be 0 for better
// reproducibility.
class Random {
 public:
  static Random& instance();
  std::default_random_engine& rng() { return rng_; }
  void Reset();

 private:
  explicit Random(bool fixed_seed);

  const bool fixed_seed_;
  std::default_random_engine rng_;
};

inline std::default_random_engine& GetRNG() { return Random::instance().rng(); }

// Returns a sorted list of the files in directory 'dir' whose filenames start
// with 'prefix'.
std::vector<std::filesystem::path> GetMatchingFiles(absl::string_view dir,
                                                    absl::string_view prefix);

// Reads a CSV file that contains a distribution. Such a file has a single line;
// the columns represent the relative frequency with which the corresponding
// input occurs. The function returns a vector whose entries correspond to the
// columns in the CSV file.
std::vector<double> ReadDistributionFile(std::filesystem::path file);

// Similar to ReadDistributionFile, except this function accepts file that has
// multiple lines. Each line converts to a vector of string, separated by the
// delimiter.
std::vector<std::vector<std::string>> ReadCsv(std::filesystem::path file,
                                              char delimiter);

// Returns the runtime path of a runfile in the fleetbench directory.
std::string GetFleetbenchRuntimePath(const absl::string_view path);

}  // namespace fleetbench
#endif  // THIRD_PARTY_FLEETBENCH_COMMON_COMMON_H_
