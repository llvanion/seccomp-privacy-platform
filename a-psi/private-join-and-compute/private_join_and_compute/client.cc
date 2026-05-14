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

#include <algorithm>
#include <iostream>
#include <memory>
#include <ostream>
#include <string>
#include <utility>

#include "absl/flags/flag.h"
#include "absl/flags/parse.h"
#include "absl/strings/str_cat.h"
#include "include/grpc/grpc_security_constants.h"
#include "include/grpcpp/channel.h"
#include "include/grpcpp/client_context.h"
#include "include/grpcpp/create_channel.h"
#include "include/grpcpp/grpcpp.h"
#include "include/grpcpp/security/credentials.h"
#include "include/grpcpp/support/sync_stream.h"
#include "include/grpcpp/support/status.h"
#include "private_join_and_compute/client_impl.h"
#include "private_join_and_compute/data_util.h"
#include "private_join_and_compute/private_join_and_compute.grpc.pb.h"
#include "private_join_and_compute/private_join_and_compute.pb.h"
#include "private_join_and_compute/protocol_client.h"
#include "private_join_and_compute/util/status.inc"
#include "include/grpcpp/support/channel_arguments.h"




ABSL_FLAG(int32_t, grpc_max_message_mb, 512,
          "Maximum gRPC send/receive message size in MB.");
ABSL_FLAG(int32_t, grpc_stream_chunk_elements, 4096,
          "Encrypted elements per gRPC streaming frame. Set to 0 to use the "
          "legacy unary RPC.");
ABSL_FLAG(std::string, port, "0.0.0.0:10501",
          "Port on which to contact server");
ABSL_FLAG(std::string, client_data_file, "",
          "The file from which to read the client database.");
ABSL_FLAG(
    int32_t, paillier_modulus_size, 1536,
    "The bit-length of the modulus to use for Paillier encryption. The modulus "
    "will be the product of two safe primes, each of size "
    "paillier_modulus_size/2.");

namespace private_join_and_compute {
namespace {

class InvokeServerHandleClientMessageSink : public MessageSink<ClientMessage> {
 public:
  explicit InvokeServerHandleClientMessageSink(
      std::unique_ptr<PrivateJoinAndComputeRpc::Stub> stub)
      : stub_(std::move(stub)) {}

  ~InvokeServerHandleClientMessageSink() override = default;

  Status Send(const ClientMessage& message) override {
    ::grpc::ClientContext client_context;
    ::grpc::Status grpc_status =
        stub_->Handle(&client_context, message, &last_server_response_);
    if (grpc_status.ok()) {
      return OkStatus();
    } else {
      return InternalError(absl::StrCat(
          "GrpcClientMessageSink: Failed to send message, error code: ",
          grpc_status.error_code(),
          ", error_message: ", grpc_status.error_message()));
    }
  }

  const ServerMessage& last_server_response() { return last_server_response_; }

 private:
  std::unique_ptr<PrivateJoinAndComputeRpc::Stub> stub_;
  ServerMessage last_server_response_;
};

void AppendServerRoundOneFrameToMessage(
    const ServerRoundOneFrame& frame, ServerMessage* server_message) {
  auto* round_one = server_message->mutable_private_intersection_sum_server_message()
                        ->mutable_server_round_one();
  for (const EncryptedElement& element : frame.encrypted_set_elements()) {
    *round_one->mutable_encrypted_set()->add_elements() = element;
  }
}

class InvokeServerHandleStreamClientMessageSink
    : public MessageSink<ClientMessage> {
 public:
  InvokeServerHandleStreamClientMessageSink(
      ::grpc::ClientReaderWriter<ClientMessageFrame, ServerMessageFrame>* stream,
      int32_t stream_chunk_elements)
      : stream_(stream),
        stream_chunk_elements_(
            stream_chunk_elements > 0 ? stream_chunk_elements : 4096) {}

  ~InvokeServerHandleStreamClientMessageSink() override = default;

  Status Send(const ClientMessage& message) override {
    Status write_status = WriteClientMessageFrames(message);
    if (!write_status.ok()) {
      return write_status;
    }
    return ReadServerMessageFrames();
  }

  const ServerMessage& last_server_response() { return last_server_response_; }

 private:
  Status WriteClientMessageFrames(const ClientMessage& message) {
    if (!message.has_private_intersection_sum_client_message() ||
        !message.private_intersection_sum_client_message()
             .has_client_round_one()) {
      ClientMessageFrame frame;
      *frame.mutable_complete_message() = message;
      return stream_->Write(frame) ? OkStatus()
                                   : InternalError("Failed to write stream.");
    }

    const auto& round_one =
        message.private_intersection_sum_client_message().client_round_one();
    const auto& encrypted_elements = round_one.encrypted_set().elements();
    const auto& reencrypted_elements = round_one.reencrypted_set().elements();
    const int encrypted_total = encrypted_elements.size();
    const int reencrypted_total = reencrypted_elements.size();
    const int total = std::max(encrypted_total, reencrypted_total);

    if (total == 0) {
      ClientMessageFrame frame;
      auto* round_one_frame = frame.mutable_client_round_one_frame();
      *round_one_frame->mutable_public_key() = round_one.public_key();
      round_one_frame->set_end_of_message(true);
      return stream_->Write(frame) ? OkStatus()
                                   : InternalError("Failed to write stream.");
    }

    bool first_frame = true;
    for (int offset = 0; offset < total; offset += stream_chunk_elements_) {
      ClientMessageFrame frame;
      auto* round_one_frame = frame.mutable_client_round_one_frame();
      if (first_frame) {
        *round_one_frame->mutable_public_key() = round_one.public_key();
        first_frame = false;
      }

      const int encrypted_end =
          std::min(offset + stream_chunk_elements_, encrypted_total);
      for (int i = offset; i < encrypted_end; ++i) {
        *round_one_frame->add_encrypted_set_elements() =
            encrypted_elements.Get(i);
      }

      const int reencrypted_end =
          std::min(offset + stream_chunk_elements_, reencrypted_total);
      for (int i = offset; i < reencrypted_end; ++i) {
        *round_one_frame->add_reencrypted_set_elements() =
            reencrypted_elements.Get(i);
      }

      round_one_frame->set_end_of_message(
          encrypted_end == encrypted_total &&
          reencrypted_end == reencrypted_total);
      if (!stream_->Write(frame)) {
        return InternalError("Failed to write stream.");
      }
    }
    return OkStatus();
  }

  Status ReadServerMessageFrames() {
    ServerMessageFrame frame;
    ServerMessage assembled_response;
    bool assembling_server_round_one = false;

    while (stream_->Read(&frame)) {
      if (frame.has_complete_message()) {
        last_server_response_ = frame.complete_message();
        return OkStatus();
      }

      if (frame.has_server_round_one_frame()) {
        assembling_server_round_one = true;
        AppendServerRoundOneFrameToMessage(frame.server_round_one_frame(),
                                           &assembled_response);
        if (frame.server_round_one_frame().end_of_message()) {
          last_server_response_ = assembled_response;
          return OkStatus();
        }
        continue;
      }

      return InvalidArgumentError("Received an empty stream frame.");
    }

    if (assembling_server_round_one) {
      return InternalError("Server stream closed mid ServerRoundOne message.");
    }
    return InternalError("Server stream closed before a response was received.");
  }

  ::grpc::ClientReaderWriter<ClientMessageFrame, ServerMessageFrame>* stream_ =
      nullptr;
  int32_t stream_chunk_elements_;
  ServerMessage last_server_response_;
};

int ExecuteProtocol() {
  ::private_join_and_compute::Context context;

  std::cout << "Client: Loading data..." << std::endl;
  auto maybe_client_identifiers_and_associated_values =
      ::private_join_and_compute::ReadClientDatasetFromFile(
          absl::GetFlag(FLAGS_client_data_file), &context);
  if (!maybe_client_identifiers_and_associated_values.ok()) {
    std::cerr << "Client::ExecuteProtocol: failed "
              << maybe_client_identifiers_and_associated_values.status()
              << std::endl;
    return 1;
  }
  auto client_identifiers_and_associated_values =
      std::move(maybe_client_identifiers_and_associated_values.value());

  std::cout << "Client: Generating keys..." << std::endl;
  std::unique_ptr<::private_join_and_compute::ProtocolClient> client =
      std::make_unique<
          ::private_join_and_compute::PrivateIntersectionSumProtocolClientImpl>(
          &context, std::move(client_identifiers_and_associated_values.first),
          std::move(client_identifiers_and_associated_values.second),
          absl::GetFlag(FLAGS_paillier_modulus_size));

  // Consider grpc::SslServerCredentials if not running locally.
  const int max_message_bytes =
      absl::GetFlag(FLAGS_grpc_max_message_mb) * 1024 * 1024;

  ::grpc::ChannelArguments channel_args;
  channel_args.SetMaxReceiveMessageSize(max_message_bytes);
  channel_args.SetMaxSendMessageSize(max_message_bytes);

  auto channel = ::grpc::CreateCustomChannel(
      absl::GetFlag(FLAGS_port),
      ::grpc::experimental::LocalCredentials(grpc_local_connect_type::LOCAL_TCP),
      channel_args);

  std::unique_ptr<PrivateJoinAndComputeRpc::Stub> stub =
      PrivateJoinAndComputeRpc::NewStub(channel);
  std::unique_ptr<::grpc::ClientContext> stream_client_context;
  std::unique_ptr<
      ::grpc::ClientReaderWriter<ClientMessageFrame, ServerMessageFrame>>
      stream;

  const int stream_chunk_elements =
      absl::GetFlag(FLAGS_grpc_stream_chunk_elements);
  std::unique_ptr<MessageSink<ClientMessage>> message_sink;
  InvokeServerHandleStreamClientMessageSink* stream_message_sink = nullptr;
  InvokeServerHandleClientMessageSink* unary_message_sink = nullptr;

  if (stream_chunk_elements > 0) {
    stream_client_context = std::make_unique<::grpc::ClientContext>();
    stream = stub->HandleStream(stream_client_context.get());
    auto sink = std::make_unique<InvokeServerHandleStreamClientMessageSink>(
        stream.get(), stream_chunk_elements);
    stream_message_sink = sink.get();
    message_sink = std::move(sink);
  } else {
    auto sink =
        std::make_unique<InvokeServerHandleClientMessageSink>(std::move(stub));
    unary_message_sink = sink.get();
    message_sink = std::move(sink);
  }

  // Execute StartProtocol and wait for response from ServerRoundOne.
  std::cout
      << "Client: Starting the protocol." << std::endl
      << "Client: Waiting for response and encrypted set from the server..."
      << std::endl;
  auto start_protocol_status =
      client->StartProtocol(message_sink.get());
  if (!start_protocol_status.ok()) {
    std::cerr << "Client::ExecuteProtocol: failed to StartProtocol: "
              << start_protocol_status << std::endl;
    return 1;
  }
  ServerMessage server_round_one =
      stream_message_sink != nullptr
          ? stream_message_sink->last_server_response()
          : unary_message_sink->last_server_response();

  // Execute ClientRoundOne, and wait for response from ServerRoundTwo.
  std::cout
      << "Client: Received encrypted set from the server, double encrypting..."
      << std::endl;
  std::cout << "Client: Sending double encrypted server data and "
               "single-encrypted client data to the server."
            << std::endl
            << "Client: Waiting for encrypted intersection sum..." << std::endl;
  auto client_round_one_status =
      client->Handle(server_round_one, message_sink.get());
  if (!client_round_one_status.ok()) {
    std::cerr << "Client::ExecuteProtocol: failed to ReEncryptSet: "
              << client_round_one_status << std::endl;
    return 1;
  }

  // Execute ServerRoundTwo.
  std::cout << "Client: Sending double encrypted server data and "
               "single-encrypted client data to the server."
            << std::endl
            << "Client: Waiting for encrypted intersection sum..." << std::endl;
  ServerMessage server_round_two =
      stream_message_sink != nullptr
          ? stream_message_sink->last_server_response()
          : unary_message_sink->last_server_response();

  // Compute the intersection size and sum.
  std::cout << "Client: Received response from the server. Decrypting the "
               "intersection-sum."
            << std::endl;
  auto intersection_size_and_sum_status =
      client->Handle(server_round_two, message_sink.get());
  if (!intersection_size_and_sum_status.ok()) {
    std::cerr << "Client::ExecuteProtocol: failed to DecryptSum: "
              << intersection_size_and_sum_status << std::endl;
    return 1;
  }

  if (stream != nullptr) {
    stream->WritesDone();
    ::grpc::Status grpc_status = stream->Finish();
    if (!grpc_status.ok()) {
      std::cerr << "Client::ExecuteProtocol: streaming RPC failed, error code: "
                << grpc_status.error_code()
                << ", error_message: " << grpc_status.error_message()
                << std::endl;
      return 1;
    }
  }

  // Output the result.
  auto client_print_output_status = client->PrintOutput();
  if (!client_print_output_status.ok()) {
    std::cerr << "Client::ExecuteProtocol: failed to PrintOutput: "
              << client_print_output_status << std::endl;
    return 1;
  }

  return 0;
}

}  // namespace
}  // namespace private_join_and_compute

int main(int argc, char** argv) {
  absl::ParseCommandLine(argc, argv);

  return private_join_and_compute::ExecuteProtocol();
}
