# Server-Client API Documentation

## 1. Overview
The communication between the client and server relies on a long-lived **WebSocket** connection. The data exchanged is serialized into binary form using Python's native **`pickle`** library, then transmitted over WebSocket. 

## 2. General Message Envelope
Both request and response payloads use a consistent message envelope structure:

```python
{
    "type": "<MsgType>",       # required: The operation or instruction type
    "sid": "<service_id>",     # required: The unique identifier for an SSE service instance
    "content": b"<...>",       # optional: The core payload (bytes from pickle or natives)
    # ...other metadata like token_digest, request_id based on the instruction type
}
```

The server manages a state machine for each `sid`:
- `NOT_EXISTS (0)`
- `CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED (1)` 
- `ALL_READY (2)`

---

## 3. Operations / API Endpoints

### 3.1 INIT (Initialization Handshake)
- **Purpose**: Sent when establishing the WebSocket connection to activate or initialize the service session on the server.
- **Request**:
  - `type`: `init`
  - `sid`: `<service_id>`
  - `content`: (None)
- **Response**:
  - `type`: `init`
  - `content` (Pickled): `{"ok": True, "state": <ServiceState Integer>}`

### 3.2 CONFIG (Upload Configuration)
- **Purpose**: Uploads SSE configuration details to the server. Must be preceded by `INIT`.
- **Request**:
  - `type`: `config`
  - `content` (Pickled): Native Python dictionary containing configuration data.
- **Response**:
  - `type`: `config`
  - `content` (Pickled): `{"ok": True}`

### 3.3 UPLOAD_DB (Upload Encrypted Database)
- **Purpose**: Uploads the client-side encrypted database (EDB) to the server for persistence.
- **Request**:
  - `type`: `upload_edb`
  - `content`: Unpickled native `bytes` from serializing the EDB itself.
- **Response**:
  - `type`: `upload_edb`
  - `content` (Pickled): `{"ok": True}` or `{"ok": False, "reason": "..."}`

### 3.4 TOKEN (Single Search Query)
- **Purpose**: Issues a single search query using an SSE Search Token.
- **Request**:
  - `type`: `token`
  - `content`: Native `bytes` array representing the serialized `SSEToken`.
  - Additional field: `token_digest` (e.g., MD5 string of token)
- **Response**:
  - `type`: `result`
  - `content`: Native `bytes` containing the serialized search results or Pickled dict `{"ok": False, "reason": "..."}` on error.
  - Additional field: Returns `token_digest` as received.

### 3.5 MULTI_TOKEN (Batch Search Query)
- **Purpose**: Bulk dispatch multiple Search Tokens to reduce network overhead in multi-keyword searches.
- **Request**:
  - `type`: `multi_token`
  - `content` (Pickled): `{"tokens": [{"token_bytes": b"...", "token_digest": "..."}, ...]}`
  - Additional field: `request_id` (UUID string)
- **Response**:
  - `type`: `multi_result`
  - `content` (Pickled): `{ "ok": True, "results": [ {"token_digest": "...", "result": b"<...>"}, ... ] }`
  - Additional field: Returns `request_id` as received.

### 3.6 DELETE (Delete Data)
- **Purpose**: Removes specific entries in the encrypted DB.
- **Request**:
  - `type`: `delete`
  - `content` (Pickled): `{ "token_bytes": b"<...>" (optional), "indices": [<int>, ...] (optional) }`
  - Additional field: `request_id` (UUID string)
- **Response**:
  - `type`: `delete_result`
  - `content` (Pickled): `{"ok": True, "deleted_count": <int>}`
  - Additional field: Returns `request_id` as received.

### 3.7 UPDATE (Update / Insert Data)
- **Purpose**: Adds or modifies ciphertexts in the encrypted database.
- **Request**:
  - `type`: `update`
  - `content` (Pickled): 
    ```python
    {
       "token_bytes": b"<...>",   # (optional)
       "encrypted_data": ANY,     # Ciphertext list or items
       "entries": [{"addr": ANY, "value": ANY}, ...] # (optional) Direct address bindings
    }
    ```
  - Additional field: `request_id` (UUID string)
- **Response**:
  - `type`: `update_result`
  - `content` (Pickled): `{"ok": True, "updated_count": <int>}`
  - Additional field: Returns `request_id` as received.

### 3.8 CONTROL (Server Control Event)
- **Purpose**: Unsolicited server-side push events (e.g. for connection eviction, warnings).
- **Request**: None (Server initiated)
- **Response**:
  - `type`: `control`
  - `content`: UTF-8 encoded `bytes` containing the message string.