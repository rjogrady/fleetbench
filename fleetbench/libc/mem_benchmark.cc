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

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <random>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include "absl/log/check.h"
#include "absl/random/distributions.h"
#include "absl/strings/str_cat.h"
#include "absl/strings/string_view.h"
#include "benchmark/benchmark.h"
#include "fleetbench/common/common.h"
#include "fleetbench/dynamic_registrar.h"
#include "fleetbench/libc/utils.h"

namespace fleetbench {
namespace libc {
// Number of needed buffer of memory operators.
static constexpr size_t kMemcpyBufferCount = 2;
static constexpr size_t kMemmoveBufferCount = 3;
static constexpr size_t kMemsetBufferCount = 1;
static constexpr size_t kMemcmpBufferCount = 2;
static constexpr size_t kBcmpBufferCount = 2;

// The chance that two memory buffers are exactly same -- memcmp/bcmp only.
static constexpr float kComparisonEqual = 0.4;

// Whether a memory function is to be considered as "comparing bytes"
// (memcmp/bcmp only). This is useful when generating buffers so we can test
// effect of buffers comparing equal or different.
enum class IsCompare : bool { YES = true, NO = false };

// KibiByte. 1kKiB = 1024 bytes
static constexpr int64_t kKiB = 1024;

// Reserved space for the benchmarking framework to operate (otherwise it will
// evict our buffers from current cache).
static constexpr int64_t kReservedBenchmarkBytes = 1 * kKiB;

// Reserved space for precomputed parameters for memory operation.
static constexpr int64_t kPrecomputeParametersBytes = 4 * kKiB;

using CacheInfo = benchmark::CPUInfo::CacheInfo;

// Helper function to create non cache resident benchmark.
// By keeping incrementing the offset, we explore all the memory of a given
// buffer, which increases the cache miss chance of the previous cache level.
// The function updates the `offset_` value stored in `buffer`.
void CalculateSpan(MemoryBuffers *buffer, const BM_Mem_Parameters &parameters,
                   const size_t buffer_size) {
  size_t offset = buffer->get_offset();
  offset += parameters.offset + parameters.size_bytes;
  if (offset + parameters.size_bytes >= buffer_size) offset = 0;
  buffer->set_offset(offset);
}

void MemcpyFunction(benchmark::State &state,
                    std::vector<BM_Mem_Parameters> &parameters,
                    const size_t buffer_size) {
  MemoryBuffers buffers(buffer_size);
  size_t batch_size = parameters.size();
  // Run benchmark and call memcpy function
  while (state.KeepRunningBatch(batch_size)) {
    for (auto &p : parameters) {
      CalculateSpan(&buffers, p, buffer_size);
      auto res = memcpy(buffers.dst(), buffers.src(), p.size_bytes);
      benchmark::DoNotOptimize(res);
    }
  }
}

void MemmoveFunction(benchmark::State &state,
                     std::vector<BM_Mem_Parameters> &parameters,
                     const size_t buffer_size) {
  // |----------|----------|----------|
  // |<--src1-->|<--src2-->|<--src3-->|
  //            ↑
  //           dst
  // The memmove function allows the src and dst buffers to overlap. To
  // reproduce this behavior we will use only one of the two buffers allocated
  // by MemoryBuffers below. Both src and dst pointers will be selected from the
  // dst() member.
  // We want to exercise three configurations :
  //    1. src and dst overlap, src is before dst
  //    2. src and dst overlap, src is after dst
  //    3. src and dst do not overlap
  // To do so, we allocate a memory region of size '3 * buffer_size' and we pin
  // the dst pointer to a third of the buffer. Then we allow src to be anywhere
  // in the buffer as long as it doesn't read past allocated memory. This way
  // src will fall into one of the three regions: src1 corresponds to case 1
  // above, src2 to case 2, src3 to case 3. The number of bytes to be moved is
  // always smaller than buffer_size.
  MemoryBuffers buffers(buffer_size * 3);
  size_t batch_size = parameters.size();
  // Run benchmark and call memmove function
  while (state.KeepRunningBatch(batch_size)) {
    for (auto &p : parameters) {
      CalculateSpan(&buffers, p, buffer_size);
      auto res =
          memmove(buffers.dst(buffers.size() / 3), buffers.dst(), p.size_bytes);
      benchmark::DoNotOptimize(res);
    }
  }
}

void MemcmpFunction(benchmark::State &state,
                    std::vector<BM_Mem_Parameters> &parameters,
                    const size_t buffer_size) {
  MemoryBuffers buffers(buffer_size);
  size_t batch_size = parameters.size();
  // Run benchmark and call memcmp function
  while (state.KeepRunningBatch(batch_size)) {
    for (auto &p : parameters) {
      CalculateSpan(&buffers, p, buffer_size);
      buffers.mark_dst(p.offset);
      auto res = memcmp(buffers.dst(), buffers.src(), p.size_bytes);
      benchmark::DoNotOptimize(res);
      buffers.reset_dst(p.offset);
    }
  }
}

void BcmpFunction(benchmark::State &state,
                  std::vector<BM_Mem_Parameters> &parameters,
                  const size_t buffer_size) {
  MemoryBuffers buffers(buffer_size);
  size_t batch_size = parameters.size();
  // Run benchmark and call bcmp function
  while (state.KeepRunningBatch(batch_size)) {
    for (auto &p : parameters) {
      CalculateSpan(&buffers, p, buffer_size);
      buffers.mark_dst(p.offset);
      auto res = bcmp(buffers.dst(), buffers.src(), p.size_bytes);
      benchmark::DoNotOptimize(res);
      buffers.reset_dst(p.offset);
    }
  }
}

void MemsetFunction(benchmark::State &state,
                    std::vector<BM_Mem_Parameters> &parameters,
                    const size_t buffer_size) {
  MemoryBuffers buffers(buffer_size);
  size_t batch_size = parameters.size();
  // Run benchmark and call memset function
  while (state.KeepRunningBatch(batch_size)) {
    for (auto &p : parameters) {
      CalculateSpan(&buffers, p, buffer_size);
      auto res = memset(buffers.dst(), p.offset % 0xFF, p.size_bytes);
      benchmark::DoNotOptimize(res);
    }
  }
}

// Returns a sorted list of the files for the distributions whose filenames
// start with 'prefix'.
static std::vector<std::filesystem::path> GetDistributionFiles(
    absl::string_view prefix) {
  auto p = std::filesystem::path(__FILE__).replace_filename("distributions");
  return GetMatchingFiles(p, prefix);
}

static int GetCacheSize(size_t cache_level, absl::string_view cache_type = "") {
  for (const CacheInfo &ci : benchmark::CPUInfo::Get().caches) {
    if (ci.level == cache_level) {
      if ((cache_level == 1 && ci.type == cache_type) || (cache_level > 1))
        return ci.size;
    }
  }
  return -1;
}

static void BM_Memory(benchmark::State &state,
                      const std::vector<double> &memory_size_distribution,
                      size_t buffer_count,
                      void (*memory_call)(benchmark::State &,
                                          std::vector<BM_Mem_Parameters> &,
                                          const size_t),
                      const IsCompare &is_compare, const size_t cache_size) {
  // Remaining available memory size in current cache for needed parameters to
  // run benchmark.
  const size_t available_bytes =
      cache_size - kPrecomputeParametersBytes - kReservedBenchmarkBytes;

  const size_t batch_size = 1000;

  // Pre-calculates parameter values.
  std::vector<BM_Mem_Parameters> parameters(batch_size);

  // Convert prod size distribution to a discrete distribution.
  std::discrete_distribution<uint16_t> size_bytes_sampler(
      memory_size_distribution.begin(), memory_size_distribution.end());

  // Max buffer size can be stored in current cache.
  const size_t buffer_size = available_bytes / buffer_count;

  for (auto &p : parameters) {
    // Size_bytes is sampled from collected prod distribution.
    p.size_bytes = size_bytes_sampler(GetRNG());

    // Once we have size_bytes, we can sample the offsets from a discrete
    // uniform distribution in interval [0, offset_upper_bound), where
    // 'offset_upper_bound' is calculated by subtracting size_bytes from
    // maximum buffer size to avoid accessing past the end of the buffer.
    const size_t offset_upper_bound = buffer_size - p.size_bytes;

    if (is_compare == IsCompare::YES) {
      // For memcmp/bcmp, the offset indicates the position of the first
      // mismatch char between the two buffers. The value of offset indicates:
      //  0 : Buffers always compare equal,
      // >0 : Buffers compare different at 'byte = offset - 1'.
      const bool is_identical = absl::Bernoulli(GetRNG(), kComparisonEqual);
      if (is_identical) {
        p.offset = 0;
      } else {
        // +1 is to make up the missing '0' used earlier to indicate equal
        // buffers. That is, if p.offset = 1, the mismatch is at index 0.
        p.offset = absl::Uniform<uint16_t>(GetRNG(), 0, p.size_bytes);
        p.offset += 1;
        CHECK_LT(p.offset, buffer_size) << "May result in buffer overflow";
      }
    } else {
      // For non-comparison operation, offset is used to calculate the starting
      // position of the memory block.
      p.offset = absl::Uniform<uint16_t>(GetRNG(), 0, offset_upper_bound);

      // Check offset is valid.
      CHECK_LT(p.offset + p.size_bytes, buffer_size)
          << "May result in src buffer overflow";
    }
  }

  memory_call(state, parameters, buffer_size);

  // Make each benchmark repetition reproducible, if using a fixed seed.
  Random::instance().Reset();

  // Computes the total_types throughput.
  size_t batch_bytes = 0;
  for (auto &P : parameters) {
    batch_bytes += P.size_bytes;
  }

  const size_t total_bytes = (state.iterations() * batch_bytes) / batch_size;

  state.SetBytesProcessed(total_bytes);
  state.counters["bytes_per_cycle"] = benchmark::Counter(
      total_bytes / benchmark::CPUInfo::Get().cycles_per_second,
      benchmark::Counter::kIsRate);
  state.counters["bytes"] =
      benchmark::Counter(total_bytes, benchmark::Counter::kDefaults);
}

void RegisterBenchmarks() {
  using operation_entry =
      std::tuple<std::string, size_t,
                 void (*)(benchmark::State &, std::vector<BM_Mem_Parameters> &,
                          const size_t),
                 IsCompare>;
  auto memory_operations = {
      operation_entry("Memcpy", kMemcpyBufferCount, &MemcpyFunction,
                      IsCompare::NO),
      operation_entry("Memmove", kMemmoveBufferCount, &MemmoveFunction,
                      IsCompare::NO),
      operation_entry("Memcmp", kMemcmpBufferCount, &MemcmpFunction,
                      IsCompare::YES),
      operation_entry("Bcmp", kBcmpBufferCount, &BcmpFunction, IsCompare::YES),
      operation_entry("Memset", kMemsetBufferCount, &MemsetFunction,
                      IsCompare::NO),
  };
  auto cache_resident_info = {
      std::make_pair("L1", GetCacheSize(1, "Data")),
      std::make_pair("L2", GetCacheSize(2)),
      std::make_pair("LLC", GetCacheSize(3)),
      std::make_pair("Cold", 2 * GetCacheSize(3)),
  };
  auto memory_benchmark = fleetbench::libc::BM_Memory;
  for (const auto &[distribution_file_prefix, buffer_counter, memory_function,
                    is_compare] : memory_operations) {
    const auto &files = GetDistributionFiles(distribution_file_prefix);
    for (const auto &file : files) {
      auto distribution_name = file.filename().string();
      distribution_name.erase(distribution_name.find(".csv"));
      distribution_name.replace(distribution_name.find("Google"), 6, "-");

      const std::vector<double> memory_size_distribution =
          ReadDistributionFile(file);
      for (const auto &[cache_name, cache_size] : cache_resident_info) {
        std::string benchmark_name =
            absl::StrCat("BM_", distribution_name, "_", cache_name);
        benchmark::RegisterBenchmark(benchmark_name.c_str(), memory_benchmark,
                                     memory_size_distribution, buffer_counter,
                                     memory_function, is_compare, cache_size);
      }
    }
  }
}

class BenchmarkRegisterer {
 public:
  BenchmarkRegisterer() {
    DynamicRegistrar::Get()->AddCallback(RegisterBenchmarks);
    DynamicRegistrar::Get()->AddDefaultFilter("BM_Bcmp-Fleet_L1");
    DynamicRegistrar::Get()->AddDefaultFilter("BM_Memcmp-Fleet_L1");
    DynamicRegistrar::Get()->AddDefaultFilter("BM_Memcpy-Fleet_L1");
    DynamicRegistrar::Get()->AddDefaultFilter("BM_Memmove-Fleet_L1");
    DynamicRegistrar::Get()->AddDefaultFilter("BM_Memset-Fleet_L1");
  }
};

BenchmarkRegisterer br;

}  // namespace libc
}  // namespace fleetbench
