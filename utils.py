from __future__ import print_function, division
import sys
import os

sys.path.append(os.path.abspath("."))
sys.dont_write_bytecode = True

import csv
import numpy as np
from collections import Counter
from sklearn.utils import shuffle, class_weight
from tensorflow.keras.utils import to_categorical

FLOAT_ERROR = 1.0e-8
OVER_SAMPLER_RATE = 0.1
UNDER_SAMPLER_RATE = 0.5

def read_csv_file(file_path, as_singles=False, as_string=False):
  lines = []
  with open(file_path) as f:
    if as_string:
      csv_reader = csv.reader(f)
    else:
      csv_reader = csv.reader(f, quoting=csv.QUOTE_NONNUMERIC)
    for line in csv_reader:
      if as_singles:
        lines.append(line[0])
      else:
        lines.append(line)
    return lines


def dump_labels_to_csv(labels, file_path):
  labels = np.array(list(map(int, labels)))
  labels.tofile(file_path, sep='\n')


def get_data_files_suffix(base_folder, prefixes, suffix):
  file_paths = []
  for prefix in prefixes:
    file_paths.append(os.path.join(base_folder, "%s%s.csv" % (prefix, suffix)))
  return file_paths


def get_data_files(base_folder, prefixes, skip_y=False):
  return {
    "x": get_data_files_suffix(base_folder, prefixes, "x"),
    "y": None if skip_y else get_data_files_suffix(base_folder, prefixes, "y"),
    "x_time": get_data_files_suffix(base_folder, prefixes, "x_time"),
    "y_time": get_data_files_suffix(base_folder, prefixes, "y_time")
  }


class SamplingRate:
  def __init__(self, intervals, x_start, window_skip, step_size):
    self.intervals = intervals
    self.x_start = x_start
    self.window_skip = window_skip
    self.step_size = step_size
    self.window_size = len(intervals)

class DataStreamer:
  def __init__(self, data_files, sample_deltas=None, do_shuffle=False,
               class_balancer=None, batch_size=1, n_labels=None):
    self.x_files = data_files["x"]
    self.y_files = data_files.get("y", None)
    self.x_time_files = data_files.get("x_time", None)
    self.y_time_files = data_files.get("y_time", None)
    self.features = None
    self.feature_times = None
    self.n_features = None
    self.labels = None
    self.label_times = None
    self.x_index = self.y_index = 0
    self.n_samples = 0
    self.sample_deltas = sample_deltas
    self.do_shuffle = do_shuffle
    self.class_balancer = class_balancer
    self.label_histogram = None
    self.batch_size = batch_size
    self.index = None
    self.sample_weights = None
    self.class_weights = None
    self.classes = None
    self.initialize()

  def initialize(self):
    self.features = []
    feature_times = []
    self.labels = []
    label_times = []
    for file_index, x_file_path in enumerate(self.x_files):
      features = read_csv_file(x_file_path)
      self.n_features = len(features[0])
      if self.y_files:
        self.labels += read_csv_file(self.y_files[file_index], as_singles=True, as_string=True)
      if self.x_time_files:
        feature_times = read_csv_file(self.x_time_files[file_index], as_singles=True)
      if self.y_time_files:
        label_times = read_csv_file(self.y_time_files[file_index], as_singles=True)
        self.n_samples += len(label_times)
      x_index = self.sample_deltas.x_start
      for y_index, y_time in enumerate(label_times):
        y_time = float(y_time)
        samples = []
        window_index = max(x_index, 0)
        for delta in self.sample_deltas.intervals:
          x_time = float(feature_times[window_index])
          if window_index < len(feature_times) and abs(y_time + delta - x_time) <= FLOAT_ERROR:
            samples.append(features[window_index])
            window_index += self.sample_deltas.window_skip
          else:
            samples.append([0.0] * len(features[0]))
        x_index += self.sample_deltas.step_size
        self.features.append(samples)
    self.features = np.array(self.features)
    if len(self.labels):
      self.labels = np.array(self.labels)
    if self.do_shuffle:
      if len(self.labels):
        self.features, self.labels = shuffle(self.features, self.labels)
      else:
        self.features = shuffle(self.features)
    if len(self.labels) and self.class_balancer is not None:
      self.features, self.labels = self.class_balancer.balance(self.features, self.labels)
    self.index = 0
    if len(self.labels):
      cntr = Counter(self.labels)
      self.classes = sorted(cntr.keys())
      self.sample_weights = class_weight.compute_sample_weight("balanced", y=self.labels)
      self.class_weights = class_weight.compute_class_weight("balanced", classes=self.classes, y=self.labels)

  def next(self):
    feature_samples = self.features[self.index : self.index + self.batch_size]
    label_samples = self.labels[self.index : self.index + self.batch_size] if self.labels is not None else None
    self.index += self.batch_size
    return feature_samples, label_samples

  def preprocess(self, n_classes=None):
    if n_classes is None:
      n_classes = len(self.classes)
    x = np.array(self.features)
    y = to_categorical(self.labels, n_classes)
    return x, y, self.sample_weights

  def generate(self):
    x = np.zeros((self.batch_size, self.n_features))
    y = np.zeros((self.batch_size, self.n_features))

