# Copyright 2024 The Fleetbench Authors
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

import os
import subprocess
from unittest import mock
from absl.testing import absltest
from absl.testing import flagsaver
from fleetbench.parallel import benchmark


class BenchmarkTest(absltest.TestCase):

  def testFindBenchmarkAbsolutePath(self):
    temp_dir = self.create_tempdir()
    temp_dir.create_file("fake_benchmark")
    benchmark_path = os.path.join(temp_dir, "fake_benchmark")
    bm = benchmark.Benchmark(benchmark_path, "BM_Test")
    self.assertEqual(bm.Name(), "fake_benchmark (BM_Test)")
    self.assertEqual(
        bm.CommandLine(), [benchmark_path, "--benchmark_filter=BM_Test$"]
    )

  def testBenchmarkDir(self):
    temp_dir = self.create_tempdir()
    temp_dir.create_file("fake_benchmark")

    with flagsaver.flagsaver(benchmark_dir=temp_dir.full_path):
      bm = benchmark.Benchmark("fake_benchmark", "BM_Test")
      self.assertEqual(bm.Name(), "fake_benchmark (BM_Test)")

  def testBenchmarkNotFound(self):
    with self.assertRaises(FileNotFoundError):
      benchmark.Benchmark("/abs/path/fake_benchmark", "BM_Test")

    with flagsaver.flagsaver(benchmark_dir="/abs/path"):
      with self.assertRaises(FileNotFoundError):
        benchmark.Benchmark("fake_benchmark", "BM_Test")

  @mock.patch.object(subprocess, "run", autospec=True)
  def testGetSubBenchmarks(self, mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="BM_Test\nBM_Test2\n", stderr=""
    )
    self.assertEqual(
        benchmark.GetSubBenchmarks("/path/to/benchmark"),
        ["BM_Test", "BM_Test2"],
    )

  def testCommandLine(self):
    temp_dir = self.create_tempdir()
    temp_dir.create_file("fake_benchmark")
    benchmark_path = os.path.join(temp_dir, "fake_benchmark")
    bm = benchmark.Benchmark(benchmark_path, "BM_Test")
    self.assertEqual(
        bm.CommandLine(),
        [benchmark_path, "--benchmark_filter=BM_Test$"],
    )

    bm.AddCommandFlags(["--benchmark_min_time=10"])

    self.assertEqual(
        bm.CommandLine(),
        [
            benchmark_path,
            "--benchmark_filter=BM_Test$",
            "--benchmark_min_time=10",
        ],
    )

    bm.AddCommandFlags(["--benchmark_perf_counters=ctr1,ctr2"])
    self.assertEqual(
        bm.CommandLine(),
        [
            benchmark_path,
            "--benchmark_filter=BM_Test$",
            "--benchmark_min_time=10",
            "--benchmark_perf_counters=ctr1,ctr2",
        ],
    )


if __name__ == "__main__":
  absltest.main()
