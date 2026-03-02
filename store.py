import os
import json
import asyncio

import frontend.client.commands as client_commands

DB_PATH = "db.json"
CONFIG_PATH = "config.json"
SSE_SCHEME = "CJJ14.PiBas"

async def init():
    client_commands.generate_default_config(SSE_SCHEME, CONFIG_PATH)

async def main():
    data = json.load(open("db.json", "r"))

    if not os.path.exists(CONFIG_PATH):
        await init()

    for key, val in data.items():
        # client_commands.create_service(CONFIG_PATH, key)
        # await client_commands.upload_config(sname=key)
        # client_commands.generate_key(sname=key)
        for k in val.keys():
            val[k] = [json.dumps(val[k]).encode().hex()]
        client_commands.encrypt_database(val, sname=key)
        await client_commands.upload_encrypted_database(sname=key)

if __name__ == "__main__":
    asyncio.run(main())