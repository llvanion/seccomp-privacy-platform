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

#include "private_join_and_compute/private_join_and_compute_rpc_impl.h"

#include <algorithm>

#include "private_join_and_compute/util/status.inc"

namespace private_join_and_compute {

namespace {
// Translates Status to grpc::Status
::grpc::Status ConvertStatus(const Status& status) {
  if (status.ok()) {
    return ::grpc::Status::OK;
  }
  if (IsInvalidArgument(status)) {
    return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT,
                          std::string(status.message()));
  }
  if (IsInternal(status)) {
    return ::grpc::Status(::grpc::StatusCode::INTERNAL,
                          std::string(status.message()));
  }
  return ::grpc::Status(::grpc::StatusCode::UNKNOWN,
                        std::string(status.message()));
}

class SingleMessageSink : public MessageSink<ServerMessage> {
 public:
  explicit SingleMessageSink(ServerMessage* server_message)
      : server_message_(server_message) {}

  ~SingleMessageSink() override = default;

  Status Send(const ServerMessage& server_message) override {
    if (!message_sent_) {
      *server_message_ = server_message;
      message_sent_ = true;
      return OkStatus();
    } else {
      return InvalidArgumentError(
          "SingleMessageSink can only accept a single message.");
    }
  }

 private:
  ServerMessage* server_message_ = nullptr;
  bool message_sent_ = false;
};

void AppendClientRoundOneFrameToMessage(
    const ClientRoundOneFrame& frame, ClientMessage* client_message) {
  auto* round_one = client_message->mutable_private_intersection_sum_client_message()
                        ->mutable_client_round_one();
  if (!frame.public_key().empty()) {
    *round_one->mutable_public_key() = frame.public_key();
  }
  for (const EncryptedElement& element : frame.encrypted_set_elements()) {
    *round_one->mutable_encrypted_set()->add_elements() = element;
  }
  for (const EncryptedElement& element : frame.reencrypted_set_elements()) {
    *round_one->mutable_reencrypted_set()->add_elements() = element;
  }
}

class StreamingServerMessageSink : public MessageSink<ServerMessage> {
 public:
  StreamingServerMessageSink(
      ::grpc::ServerReaderWriter<ServerMessageFrame, ClientMessageFrame>* stream,
      int32_t stream_chunk_elements)
      : stream_(stream),
        stream_chunk_elements_(
            stream_chunk_elements > 0 ? stream_chunk_elements : 4096) {}

  ~StreamingServerMessageSink() override = default;

  Status Send(const ServerMessage& server_message) override {
    if (!server_message.has_private_intersection_sum_server_message() ||
        !server_message.private_intersection_sum_server_message()
             .has_server_round_one()) {
      ServerMessageFrame frame;
      *frame.mutable_complete_message() = server_message;
      return stream_->Write(frame) ? OkStatus()
                                   : InternalError("Failed to write stream.");
    }

    const auto& elements =
        server_message.private_intersection_sum_server_message()
            .server_round_one()
            .encrypted_set()
            .elements();
    const int total = elements.size();
    if (total == 0) {
      ServerMessageFrame frame;
      frame.mutable_server_round_one_frame()->set_end_of_message(true);
      return stream_->Write(frame) ? OkStatus()
                                   : InternalError("Failed to write stream.");
    }

    for (int offset = 0; offset < total; offset += stream_chunk_elements_) {
      ServerMessageFrame frame;
      auto* round_one_frame = frame.mutable_server_round_one_frame();
      const int end = std::min(offset + stream_chunk_elements_, total);
      for (int i = offset; i < end; ++i) {
        *round_one_frame->add_encrypted_set_elements() = elements.Get(i);
      }
      round_one_frame->set_end_of_message(end == total);
      if (!stream_->Write(frame)) {
        return InternalError("Failed to write stream.");
      }
    }
    return OkStatus();
  }

 private:
  ::grpc::ServerReaderWriter<ServerMessageFrame, ClientMessageFrame>* stream_ =
      nullptr;
  int32_t stream_chunk_elements_;
};

}  // namespace

::grpc::Status PrivateJoinAndComputeRpcImpl::Handle(
    ::grpc::ServerContext* context, const ClientMessage* request,
    ServerMessage* response) {
  SingleMessageSink message_sink(response);
  auto status = protocol_server_impl_->Handle(*request, &message_sink);
  return ConvertStatus(status);
}

::grpc::Status PrivateJoinAndComputeRpcImpl::HandleStream(
    ::grpc::ServerContext* context,
    ::grpc::ServerReaderWriter<ServerMessageFrame, ClientMessageFrame>*
        stream) {
  ClientMessageFrame frame;
  ClientMessage pending_client_message;
  bool pending_client_round_one = false;

  while (stream->Read(&frame)) {
    if (frame.has_complete_message()) {
      StreamingServerMessageSink message_sink(stream, stream_chunk_elements_);
      auto status =
          protocol_server_impl_->Handle(frame.complete_message(), &message_sink);
      if (!status.ok()) {
        return ConvertStatus(status);
      }
      continue;
    }

    if (frame.has_client_round_one_frame()) {
      pending_client_round_one = true;
      AppendClientRoundOneFrameToMessage(frame.client_round_one_frame(),
                                         &pending_client_message);
      if (!frame.client_round_one_frame().end_of_message()) {
        continue;
      }

      StreamingServerMessageSink message_sink(stream, stream_chunk_elements_);
      auto status =
          protocol_server_impl_->Handle(pending_client_message, &message_sink);
      if (!status.ok()) {
        return ConvertStatus(status);
      }
      pending_client_message.Clear();
      pending_client_round_one = false;
      continue;
    }

    return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT,
                          "Received an empty stream frame.");
  }

  if (pending_client_round_one) {
    return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT,
                          "Client stream closed mid ClientRoundOne message.");
  }
  return ::grpc::Status::OK;
}

}  // namespace private_join_and_compute
