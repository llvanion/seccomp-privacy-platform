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
from toolkit.record_recovery_service_config import (
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_value,
)


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


@cli.command()
@click.option("--source-path", help='plaintext local source path')
@click.option("--out-path", help='encrypted record store path')
@click.option("--source-format", type=click.Choice(["jsonl", "csv"]), default="jsonl")
@click.option("--record-id-field", help='source record field used as encrypted store record id')
@click.option("--key-env", help='environment variable containing the record-store passphrase')
async def create_encrypted_record_store(source_path, out_path, source_format, record_id_field, key_env):
    if source_path is None or out_path is None or record_id_field is None or key_env is None:
        click.echo('Incomplete options')
        return

    try:
        client_commands.create_encrypted_record_store(
            source_path=source_path,
            out_path=out_path,
            source_format=source_format,
            record_id_field=record_id_field,
            key_env=key_env,
        )
    except Exception as e:
        raise click.ClickException(str(e))


@cli.command()
@click.option("--source-path", help='plaintext local source path')
@click.option("--out-path", help='bridge-ready export path')
@click.option("--role", type=click.Choice(["server", "client"]), help='bridge side role')
@click.option("--source-format", type=click.Choice(["jsonl", "csv"]), default="jsonl")
@click.option("--out-format", type=click.Choice(["jsonl", "csv"]), default="csv")
@click.option("--join-key-field", help='field name containing the join key')
@click.option("--value-field", help='field name containing the aggregate value', default='')
@click.option("--filter", "filters", multiple=True, help='repeatable field=value filter')
@click.option("--caller", help='caller identity for export policy/audit', default='local_demo')
@click.option("--policy-config", help='optional JSON export policy config', default='')
@click.option("--audit-log", help='optional export audit jsonl path', default='')
@click.option("--job-id", help='optional job id for export audit', default='')
@click.option("--tenant-id", help='tenant scope for export policy/audit', default='')
@click.option("--dataset-id", help='dataset scope for export policy/audit', default='')
@click.option("--unsafe-allow-no-policy", is_flag=True, help='allow local ad-hoc export without a policy config')
@click.option("--sse-keyword", help='optional SSE keyword used to derive candidate record IDs before export', default='')
@click.option("--record-id-field", help='source record field matched against SSE result identifiers', default='')
@click.option("--record-id-format", type=click.Choice(["int", "hex", "raw", "utf8"]), default="utf8")
@click.option("--record-store-path", help='optional encrypted record store used with --sse-keyword', default='')
@click.option("--record-store-key-env", help='environment variable containing the record-store passphrase', default='')
@click.option("--record-recovery-service-config", help='optional JSON config shared by record recovery service clients', default='')
@click.option("--record-recovery-socket", help='optional Unix socket for long-running record recovery service', default='')
@click.option("--record-recovery-auth-env", help='optional env var containing the record recovery service auth token', default='')
@click.option("--record-recovery-service-id", help='service instance id for record recovery requests', default='')
@click.option("--sid", help='SSE service id for --sse-keyword', default='')
@click.option("--sname", help='SSE service name for --sse-keyword', default='')
async def export_bridge_records(source_path, out_path, role, source_format, out_format, join_key_field, value_field, filters, caller, policy_config, audit_log, job_id, tenant_id, dataset_id, unsafe_allow_no_policy, sse_keyword, record_id_field, record_id_format, record_store_path, record_store_key_env, record_recovery_service_config, record_recovery_socket, record_recovery_auth_env, record_recovery_service_id, sid, sname):
    if out_path is None or role is None or join_key_field is None:
        click.echo('Incomplete options')
        return
    if not source_path and not record_store_path:
        click.echo('Incomplete options: --source-path or --record-store-path')
        return

    try:
        if record_recovery_service_config:
            resolved = load_resolved_record_recovery_service_config(record_recovery_service_config)
            record_recovery_service_id = merged_record_recovery_service_value(record_recovery_service_id, resolved["service_id"])
            tenant_id = merged_record_recovery_service_value(tenant_id, resolved["tenant_id"])
            dataset_id = merged_record_recovery_service_value(dataset_id, resolved["dataset_id"])
            record_recovery_socket = merged_record_recovery_service_value(record_recovery_socket, resolved["socket_path"])
            record_recovery_auth_env = merged_record_recovery_service_value(record_recovery_auth_env, resolved["auth_token_env"])
        if sse_keyword:
            if unsafe_allow_no_policy:
                raise click.ClickException("--unsafe-allow-no-policy is not allowed with --sse-keyword")
            await client_commands.export_bridge_records_from_sse(
                source_path=source_path,
                out_path=out_path,
                role=role,
                source_format=source_format,
                out_format=out_format,
                join_key_field=join_key_field,
                value_field=value_field,
                filters=list(filters),
                caller=caller,
                policy_config=policy_config,
                audit_log=audit_log,
                job_id=job_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                sse_keyword=sse_keyword,
                record_id_field=record_id_field,
                record_id_format=record_id_format,
                record_store_path=record_store_path,
                record_store_key_env=record_store_key_env,
                record_recovery_socket=record_recovery_socket,
                record_recovery_auth_env=record_recovery_auth_env,
                record_recovery_service_id=record_recovery_service_id,
                sid=sid,
                sname=sname,
            )
        else:
            client_commands.export_bridge_records(
                source_path=source_path,
                out_path=out_path,
                role=role,
                source_format=source_format,
                out_format=out_format,
                join_key_field=join_key_field,
                value_field=value_field,
                filters=list(filters),
                caller=caller,
                policy_config=policy_config,
                audit_log=audit_log,
                job_id=job_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                unsafe_allow_no_policy=unsafe_allow_no_policy,
                record_store_path=record_store_path,
                record_store_key_env=record_store_key_env,
                record_recovery_socket=record_recovery_socket,
                record_recovery_auth_env=record_recovery_auth_env,
                record_recovery_service_id=record_recovery_service_id,
            )
    except Exception as e:
        raise click.ClickException(str(e))


@cli.command()
@click.option("--config", help='optional JSON config for record recovery service runtime', default='')
@click.option("--service-id", help='service instance id for the record recovery service', default='')
@click.option("--tenant-id", help='tenant scope bound to the record recovery service', default='')
@click.option("--dataset-id", help='dataset scope bound to the record recovery service', default='')
@click.option("--socket-path", help='Unix socket path for the record recovery service')
@click.option("--socket-mode", help='octal filesystem mode for the Unix socket path', default='')
@click.option("--auth-token-env", help='optional env var containing the required auth token', default='')
@click.option("--authz-config", help='optional JSON authz policy for fine-grained service request checks', default='')
@click.option("--allowed-caller", "allowed_callers", multiple=True, help='repeatable caller identity allowlist for service requests')
@click.option("--allowed-output-root", "allowed_output_roots", multiple=True, help='repeatable allowed output root for bridge handoff writes')
@click.option("--allowed-record-store-root", "allowed_record_store_roots", multiple=True, help='repeatable allowed encrypted record-store root')
@click.option("--audit-log", help='optional service audit jsonl path', default='')
@click.option("--pid-file", help='optional file that receives the running service pid', default='')
@click.option("--ready-file", help='optional file created once the socket is ready', default='')
async def serve_record_recovery(config, service_id, tenant_id, dataset_id, socket_path, socket_mode, auth_token_env, authz_config, allowed_callers, allowed_output_roots, allowed_record_store_roots, audit_log, pid_file, ready_file):
    if config:
        try:
            resolved = load_resolved_record_recovery_service_config(config)
        except Exception as e:
            raise click.ClickException(str(e))
        service_id = merged_record_recovery_service_value(service_id, resolved["service_id"])
        tenant_id = merged_record_recovery_service_value(tenant_id, resolved["tenant_id"])
        dataset_id = merged_record_recovery_service_value(dataset_id, resolved["dataset_id"])
        socket_path = merged_record_recovery_service_value(socket_path, resolved["socket_path"])
        socket_mode = merged_record_recovery_service_value(socket_mode, resolved["socket_mode"])
        auth_token_env = merged_record_recovery_service_value(auth_token_env, resolved["auth_token_env"])
        authz_config = merged_record_recovery_service_value(authz_config, resolved["authz_config"])
        if not allowed_callers:
            allowed_callers = tuple(resolved["allowed_callers"])
        if not allowed_output_roots:
            allowed_output_roots = tuple(resolved["allowed_output_roots"])
        if not allowed_record_store_roots:
            allowed_record_store_roots = tuple(resolved["allowed_record_store_roots"])
        audit_log = audit_log or resolved["audit_log"]
        pid_file = pid_file or resolved["pid_file"]
        ready_file = ready_file or resolved["ready_file"]
    socket_mode = socket_mode or "600"

    if not socket_path:
        click.echo('Incomplete options: --socket-path')
        return

    try:
        client_commands.serve_record_recovery_service(
            service_id=service_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            socket_path=socket_path,
            socket_mode=socket_mode,
            auth_token_env=auth_token_env,
            authz_config=authz_config,
            allowed_callers=list(allowed_callers),
            allowed_output_roots=list(allowed_output_roots),
            allowed_record_store_roots=list(allowed_record_store_roots),
            audit_log=audit_log,
            pid_file=pid_file,
            ready_file=ready_file,
        )
    except Exception as e:
        raise click.ClickException(str(e))


if __name__ == '__main__':
    cli(_anyio_backend="asyncio")
