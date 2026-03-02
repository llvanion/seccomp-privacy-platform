# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: run_client.py 
@time: 2022/03/18
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description: 
"""

import asyncclick as click
import json

import frontend.client.commands as client_commands


def _parse_indices(indices_raw: str):
    if not indices_raw:
        return None
    try:
        return [int(item.strip()) for item in indices_raw.split(",") if item.strip()]
    except ValueError:
        return None


@click.group()
async def cli():
    pass


@cli.command()
@click.option("--scheme", help='name of SSE scheme')
@click.option("--save-path", help='save file path')
async def generate_config(scheme, save_path):
    if scheme is None or save_path is None:
        click.echo(f'Incomplete options')
        return
    client_commands.generate_default_config(scheme, save_path)


@cli.command()
@click.option("--config", help='file path of config')
@click.option("--sname", help='service name')
async def create_service(config, sname):
    if config is None or sname is None:
        click.echo(f'Incomplete options')
        return

    client_commands.create_service(config_path=config, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
async def upload_config(sid, sname):
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    await client_commands.upload_config(sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
async def generate_key(sid, sname):
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    client_commands.generate_key(sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--db-path", help='database path')
async def encrypt_database(sid, sname, db_path):
    if db_path is None:
        click.echo(f'Incomplete options: --db-path')
        return

    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    client_commands.encrypt_database(db_path=db_path, sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--db-path", help='multi-key database path (JSON list format)')
async def encrypt_database_multi_key(sid, sname, db_path):
    if db_path is None:
        click.echo(f'Incomplete options: --db-path')
        return

    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    client_commands.encrypt_database_multi_key(db_path=db_path, sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
async def upload_encrypted_database(sid, sname):
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return
    await client_commands.upload_encrypted_database(sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--keyword", help='keyword to search')
@click.option("--output-format",
              help='Specify the output format, which currently supports '
                   'int, hex, raw and utf8, where utf8 format output must require that'
                   ' the byte string of the file identifier must be converted from a utf8 string',
              default="raw")
async def search(sid, sname, keyword, output_format):
    if keyword is None:
        click.echo(f'Incomplete options: --keyword')
        return
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    await client_commands.search(keyword, output_format, sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--keyword", "keywords", help='keyword to search, use multiple --keyword for multi-search', multiple=True)
@click.option("--output-format",
              help='Specify output format: int, hex, raw, utf8',
              default="raw")
async def multi_search(sid, sname, keywords, output_format):
    if not keywords:
        click.echo(f'Incomplete options: --keyword (use one or more)')
        return
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    await client_commands.multi_search(list(keywords), output_format, sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--keyword", help='keyword to delete', default='')
@click.option("--indices", help='comma-separated indices, e.g. 0,1,2', default='')
async def delete_data(sid, sname, keyword, indices):
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    parsed_indices = _parse_indices(indices)
    if indices and parsed_indices is None:
        click.echo(f'Invalid --indices format, expected comma-separated integers')
        return

    if not keyword and not parsed_indices:
        click.echo(f'One of the two options --keyword or --indices must be assigned')
        return

    await client_commands.delete_data(keyword=keyword, indices=parsed_indices, sid=sid, sname=sname)


@cli.command()
@click.option("--sid", help='service id', default='')
@click.option("--sname", help='service name', default='')
@click.option("--keyword", help='keyword to update', default='')
@click.option("--entries-json", help='json array entries, e.g. [{"addr":"6161","value":"6262"}]', default='')
@click.option("--encrypted-data-hex", help='hex bytes for encrypted_data', default='')
async def update_data(sid, sname, keyword, entries_json, encrypted_data_hex):
    if not sid and not sname:
        click.echo(f'One of the two options --sid or --sname must be assigned')
        return

    entries = None
    if entries_json:
        try:
            entries = json.loads(entries_json)
            if not isinstance(entries, list):
                click.echo(f'Invalid --entries-json, expected a JSON array')
                return
        except Exception as e:
            click.echo(f'Invalid --entries-json: {e}')
            return

    encrypted_data = None
    if encrypted_data_hex:
        try:
            encrypted_data = bytes.fromhex(encrypted_data_hex)
        except ValueError:
            click.echo(f'Invalid --encrypted-data-hex, expected hex string')
            return

    if not keyword and not entries and encrypted_data is None:
        click.echo(f'At least one of --keyword / --entries-json / --encrypted-data-hex must be assigned')
        return

    await client_commands.update_data(
        keyword=keyword,
        entries=entries,
        encrypted_data=encrypted_data,
        sid=sid,
        sname=sname
    )


if __name__ == '__main__':
    cli(_anyio_backend="asyncio")
