/*
 * Copyright 2019 Google LLC.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Common implementations.

#include "private_join_and_compute/util/file.h"

#include <cstddef>
#include <cstring>
#include <initializer_list>
#include <sstream>
#include <string>

#include "absl/strings/string_view.h"

namespace private_join_and_compute {
namespace internal {
namespace {

bool IsAbsolutePath(absl::string_view path) {
  return !path.empty() && path[0] == '/';
}

bool EndsWithSlash(absl::string_view path) {
  return !path.empty() && path[path.size() - 1] == '/';
}

}  // namespace

std::string JoinPathImpl(std::initializer_list<absl::string_view> paths) {
  std::string result;

  if (paths.size() != 0) {
    // This size calculation is worst-case: it assumes one extra "/" for every
    // path other than the first.
    size_t total_size = paths.size() - 1;
    for (const absl::string_view path : paths) total_size += path.size();
    result.resize(total_size);

    auto begin = result.begin();
    auto out = begin;
    bool trailing_slash = false;
    for (absl::string_view path : paths) {
      if (path.empty()) continue;
      if (path.front() == '/') {
        if (trailing_slash) {
          path.remove_prefix(1);
        }
      } else {
        if (!trailing_slash && out != begin) *out++ = '/';
      }
      const size_t this_size = path.size();
      memcpy(&*out, path.data(), this_size);
      out += this_size;
      trailing_slash = out[-1] == '/';
    }
    result.erase(out - begin);
  }
  return result;
}

}  // namespace internal
}  // namespace private_join_and_compute
