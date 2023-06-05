# Copyright 2023 The Fleetbench Authors
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

"""This file defines a generator for synthesize benchmark corpus."""

import collections
import dataclasses
import os
import random

from absl import logging
import zstandard as zstd

from rules_python.python.runfiles import runfiles
import snappy

DATASET_DIR = (
    "com_google_fleetbench/fleetbench/compression/generate_corpora/corpora"
)

# The default window size for Snappy is 64KiB, which = 2^16
SNAPPY_WINDOW_SIZE = [16]
SNAPPY_COMPRESSION_LEVEL = [0]

# The default compression level is 3
# https://github.com/facebook/zstd/tree/7806d803383b75b00868a5367154a18caf535a92/programs#usage-of-command-line-interface
ZSTD_DECOMPRESS_COMPRESSION_LEVEL = [3]
# Default window size
# value 0 means "use default windowLog"
# https://github.com/facebook/zstd/blob/7806d803383b75b00868a5367154a18caf535a92/lib/zstd.h#L352
ZSTD_WINDOW_SIZE = [0]


@dataclasses.dataclass(frozen=True)
class CorpusChunk:
  data: bytes
  chunk_id: int
  src_file: str


@dataclasses.dataclass(frozen=True)
class CompressionParameters:
  window_size: int
  compression_level: int


def zstd_compress(input_data, compression_level):
  compressor = zstd.ZstdCompressor(level=compression_level)
  return compressor.compress(input_data)


class CorpusChunkManager:
  """A generator for synthesizing benchmark corpus."""

  def __init__(
      self,
      algorithm,
      operation,
      dataset,
      binary,
      dataset_dir=DATASET_DIR,
      chunk_size=1 * 1024,
  ):
    if algorithm == "Snappy":
      self.algorithm = "Snappy"
      self.compress_function = snappy.compress
    elif algorithm == "ZSTD":
      self.algorithm = "ZSTD"
      self.compress_function = zstd_compress
    else:
      raise RuntimeError(f"{algorithm} is not supported yet")

    self.operation = operation
    self.dataset = dataset
    self.binary = binary
    self.dataset_dir = dataset_dir
    self.chunk_size = chunk_size
    self.max_ratio_lookup = collections.defaultdict(dict)
    self.lookup_table = collections.defaultdict(dict)

    # For representative analysis
    self.benchmark_achieved_call_sizes = []
    self.benchmark_achieved_compression_ratios = []

  def generate_corpus_chunks_lookup(self):
    """Generates a lookup table to find corpus chunk based on parameters.

    This function iterates through all files in DATASET_DIR, and split the
    datasets into fixed size chunks, with the default size begin 1 KB. These
    chunks are then (de)compressed to obtain the compression parameters, i.e,
    compression ratio. Using these parameters, we create a lookup table where
    the parameters are as keys, and we can retrieve a number of chunks based on
    a specific combination of parameters.

    Raises:
      RuntimeError: not supported algorithm.
    """
    if self.algorithm == "Snappy":
      window_sizes = SNAPPY_WINDOW_SIZE
      compression_levels = SNAPPY_COMPRESSION_LEVEL
    elif self.algorithm == "ZSTD":
      # The negative compression levels offer faster compression and
      # decompression speed in exchange for some loss in compression ratio
      # compared to level 1. https://facebook.github.io/zstd/
      compression_levels = [-5, -3, -1] + list(range(0, 12)) + [15]
      window_sizes = ZSTD_WINDOW_SIZE
    else:
      raise RuntimeError(f"{self.algorithm} is not supported yet")

    # Initialize a two-levels dictionary.
    # The first level represents several compression parameters combinations:
    # compression level, window size, etc. Second level is the compersion ratio,
    # and the stored value is a list of pre-defined size (1024 bytes by default)
    # corpus hunks that satisfy the parameters combinations with the compression
    # ratio.
    compression_parameters_list = []
    compression_parameters_ratio_to_chunk = dict()
    for compression_level in compression_levels:
      for window_size in window_sizes:
        parameters = CompressionParameters(
            window_size=window_size, compression_level=compression_level
        )
        compression_parameters_list.append(parameters)
        compression_parameters_ratio_to_chunk[parameters] = (
            collections.defaultdict(list)
        )

        self.max_ratio_lookup[parameters] = 0.0

    # Iterate all corpus and collect compression parameters for each chunk
    chunk_id = 0
    for file in self.dataset:
      file_path = runfiles.Create().Rlocation(
          os.path.join(self.dataset_dir, file)
      )

      with open(file_path, "rb") as f:
        corpus = f.read()

      corpus_size = len(corpus)
      for start_idx in range(0, corpus_size, self.chunk_size):
        end_idx = start_idx + self.chunk_size

        # Discard any non chunk-size piece
        if end_idx > corpus_size:
          continue

        temp_data = corpus[start_idx:end_idx]
        corpus_chunk = CorpusChunk(
            data=temp_data, chunk_id=chunk_id, src_file=file
        )
        chunk_id += 1

        def process_chunks(data, chunk):
          # Run through all parameter combinations of designated algorithm to
          # get the compression ratio. Store the corpus chunk in the dictionary
          # where the compression parameters are keys.
          for parameters in compression_parameters_list:
            if self.algorithm == "Snappy":
              compressed_data = self.compress_function(data)
            else:
              compressed_data = self.compress_function(
                  data,
                  parameters.compression_level,
              )

            compression_ratio = self.chunk_size / len(compressed_data)

            # Trunk down ratio to aggregate data
            truncated_ratio = int(compression_ratio * 10.0) / 10.0

            # Update max compression ratio
            self.max_ratio_lookup[parameters] = max(
                truncated_ratio,
                self.max_ratio_lookup[parameters],
            )

            compression_parameters_ratio_to_chunk[parameters][
                truncated_ratio
            ].append(chunk)

        process_chunks(temp_data, corpus_chunk)

    def create_lookup_table():
      # Converts the dictionary to lookup table.
      lookup_table = collections.defaultdict(dict)

      for parameters in compression_parameters_list:
        # Create an empty list with length determined by max_ratio. We assume
        # min compression ratio is 0.0 here to avoid index conversion.
        max_ratio = self.max_ratio_lookup[parameters]
        lookup_table[parameters] = [
            [] for x in range(0, int(max_ratio * 10) + 1)
        ]

        # Generate a lookup table that with a given set of parameters
        # (compression_level, window size and compression ratio), we can
        # easily find a number of chunks that satifisfied these metrics when
        # applying compression algorithm and operation.
        for ratio in compression_parameters_ratio_to_chunk[parameters].keys():
          random.shuffle(
              compression_parameters_ratio_to_chunk[parameters][ratio]
          )
          lookup_table[parameters][int(ratio * 10)] = (
              compression_parameters_ratio_to_chunk[parameters][ratio]
          )
      return lookup_table

    self.lookup_table = create_lookup_table()

  def compute_compression_ratio(self, chunk_array, compression_level=None):
    """Calculate compression ratio when concatenating all chunks in the array."""
    if not chunk_array:
      return -1
    uncompressed_data = bytes()
    for chunk in chunk_array:
      uncompressed_data += chunk.data

    if self.algorithm == "Snappy":
      compressed_data = self.compress_function(uncompressed_data)
    else:
      compressed_data = self.compress_function(
          uncompressed_data, compression_level
      )

    compression_ratio = len(uncompressed_data) / len(compressed_data)
    return compression_ratio

  def create_chunk_array(
      self, target_call_size, target_compression_ratio, parameters
  ):
    """Select chunks from the chunk list to match target parameters.

    Greedily selecting chunks by walking through the lookup table and trying
    to match the target compression ratio. This process is done when the target
    call size, i.e, the total length of output chunks, is reached.
    At various points during this process, we also evaluate the file assembled
    so far, and adjusts the target ratio accordingly.

    Args:
      target_call_size: the target parameters we want to match
      target_compression_ratio: the target parameters we want to match
      parameters: A CompressionParameters instance consists the sampled
        compression level and window size

    Returns:
      A list of chunks.
    """
    output_chunk_array = []
    current_chunk_index = 0
    current_compression_ratio_index = int(target_compression_ratio * 10)
    max_compression_ratio_index = len(self.lookup_table[parameters])
    decrease_compression_ratio = True

    for call_size in range(0, int(target_call_size), self.chunk_size):
      # Periodically evaluate generated file so far, and adjust ratio if it's
      # necessary
      if call_size == target_call_size / 2:
        # Calculate current compression ratio and calibrate target ratio
        if self.algorithm == "Snappy":
          current_ratio = self.compute_compression_ratio(output_chunk_array)
        else:
          current_ratio = self.compute_compression_ratio(
              output_chunk_array,
              parameters.compression_level,
          )
        if current_ratio < 0:
          logging.debug("Empty chunk array")
          return None

        # Compare current_ratio to target_ratio and adjust parameters
        # accordingly.
        diff = current_ratio - target_compression_ratio
        new_compression_ratio = target_compression_ratio - diff
        new_compression_ratio_index = int(new_compression_ratio * 10)

        if new_compression_ratio_index < current_compression_ratio_index:
          if new_compression_ratio_index < 0:
            new_compression_ratio_index = 0
            decrease_compression_ratio = False
          current_compression_ratio_index = new_compression_ratio_index
          current_chunk_index = 0

      while True:
        if decrease_compression_ratio and current_compression_ratio_index < 0:
          logging.debug(
              "Fail to generate corpus, can't decrease compression ratio"
          )
          return None
        if (
            not decrease_compression_ratio
            and current_compression_ratio_index == max_compression_ratio_index
        ):
          logging.debug("Fail to generate corpus, reach max compression ratio")
          return None
        # Based on <compression_level, window_size, compression_ratio>, find
        # corresponding chunk list
        chunk_list = self.lookup_table[parameters][
            current_compression_ratio_index
        ]

        if current_chunk_index >= len(chunk_list):
          # We already used last chunk in current chunk list, update
          # compression_ratio to find new chunk list
          if decrease_compression_ratio:
            current_compression_ratio_index -= 1
          else:
            current_compression_ratio_index += 1
          current_chunk_index = 0
        else:
          # Append found data
          output_chunk_array.append(chunk_list[current_chunk_index])
          current_chunk_index += 1
          break

    return output_chunk_array

  def sample_parameters(self, distribution):
    """Sampled compression parameters from input distribution."""
    sampled_parameters = distribution.sample_child_counts()

    sampled_call_size_log2 = sampled_parameters["call_size"]
    target_call_size = 2**sampled_call_size_log2
    target_compression_ratio = sampled_parameters["compression_ratio"]

    if self.algorithm == "Snappy":
      sampled_compression_level = SNAPPY_COMPRESSION_LEVEL[0]
      sampled_window_size = SNAPPY_WINDOW_SIZE[0]
    elif self.algorithm == "ZSTD" and self.operation == "COMPRESS":
      sampled_compression_level = sampled_parameters["compression_level"]
      sampled_window_size = ZSTD_WINDOW_SIZE[0]
    elif self.algorithm == "ZSTD" and self.operation == "DECOMPRESS":
      sampled_compression_level = ZSTD_DECOMPRESS_COMPRESSION_LEVEL[0]
      sampled_window_size = ZSTD_WINDOW_SIZE[0]
    else:
      raise RuntimeError(
          f"{self.algorithm} and {self.operation} is not supported yet"
      )

    parameters = CompressionParameters(
        window_size=sampled_window_size,
        compression_level=int(sampled_compression_level),
    )
    return parameters, target_call_size, target_compression_ratio

  def generate_benchmark_corpus(self, distribution):
    """Generate fleet-representative corpus.

    We sample a set of target compression parameters from distributions, and
    create a chunk list. When concatenating all chunks from this list, the
    obtained compression parameters should be similar to the sampled ones.
    Args:
      distribution: the parameters distribution

    Returns:
      A synthesized string that is composed by several 1KiB chunks, and
      satisfies fleet compression metric distributions.
    """

    parameters, target_call_size, target_compression_ratio = (
        self.sample_parameters(distribution)
    )
    max_ratio = self.max_ratio_lookup[parameters]
    if target_compression_ratio > max_ratio:
      logging.debug(
          "Fail to generate corpus, reach max compression ratio. Max ratio from"
          " dataset is %f, whereas sampled ratio is %f",
          max_ratio,
          target_compression_ratio,
      )
      return None

    output_chunks_array = self.create_chunk_array(
        target_call_size, target_compression_ratio, parameters
    )

    if not output_chunks_array:
      return None

    # Compute final compression ratio
    random.shuffle(output_chunks_array)
    if self.algorithm == "Snappy":
      achieved_compression_ratio = CorpusChunkManager.compute_compression_ratio(
          self, output_chunks_array
      )
    else:
      achieved_compression_ratio = CorpusChunkManager.compute_compression_ratio(
          self,
          output_chunks_array,
          parameters.compression_level,
      )

    result = bytes()
    for chunk in output_chunks_array:
      result += chunk.data

    self.benchmark_achieved_call_sizes.append(len(result))
    self.benchmark_achieved_compression_ratios.append(
        int(achieved_compression_ratio * 10.0) / 10.0
    )
    logging.debug(
        "Target call size: %d, Synthesized size: %d",
        target_call_size,
        len(result),
    )

    logging.debug(
        "Target ratio: %f, achieved ratio: %f",
        target_compression_ratio,
        achieved_compression_ratio,
    )

    return result

  def generate_benchmarks(self, distribution, benchmark_nums, name, output_dir):
    """Generated fleet representative corpora and dump the results.

    Args:
      distribution: fleet compression metric distribution
      benchmark_nums: how many corpus to generate
      name: short name for a application
      output_dir: the dumped file directory
    """
    self.generate_corpus_chunks_lookup()

    file_directory = os.path.join(
        output_dir, f"{self.algorithm}-{self.operation}-{name}"
    )
    if not os.path.exists(file_directory):
      os.makedirs(file_directory)

    benchmark_id = 0
    while benchmark_id < benchmark_nums:
      result = self.generate_benchmark_corpus(distribution)
      if result is None:
        continue
      relative_filename = f"corpus_{benchmark_id}"
      filename = os.path.join(file_directory, relative_filename)
      with open(filename, "wb") as f:
        f.write(result)
      benchmark_id += 1
    print(
        f"Wrote {self.algorithm} {self.operation} {name} corpus to"
        f" {file_directory}"
    )
