from __future__ import annotations

import argparse
import asyncio
import logging
import signal


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    target_host: str,
    target_port: int,
) -> None:
    peer = client_writer.get_extra_info('peername')
    try:
        target_reader, target_writer = await asyncio.open_connection(target_host, target_port)
    except Exception as exc:
        logging.warning('connect target failed peer=%s target=%s:%s error=%s', peer, target_host, target_port, exc)
        client_writer.close()
        await client_writer.wait_closed()
        return

    logging.info('proxy connected peer=%s target=%s:%s', peer, target_host, target_port)
    try:
        await asyncio.gather(
            pipe(client_reader, target_writer),
            pipe(target_reader, client_writer),
        )
    finally:
        for writer in (client_writer, target_writer):
            writer.close()
        await asyncio.gather(
            client_writer.wait_closed(),
            target_writer.wait_closed(),
            return_exceptions=True,
        )
        logging.info('proxy closed peer=%s', peer)


async def main() -> None:
    parser = argparse.ArgumentParser(description='Small TCP proxy for Campus AI SSH gateway cutover.')
    parser.add_argument('--listen-host', default='0.0.0.0')
    parser.add_argument('--listen-port', type=int, required=True)
    parser.add_argument('--target-host', default='127.0.0.1')
    parser.add_argument('--target-port', type=int, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    server = await asyncio.start_server(
        lambda reader, writer: handle_client(
            reader,
            writer,
            target_host=args.target_host,
            target_port=args.target_port,
        ),
        args.listen_host,
        args.listen_port,
        reuse_address=True,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame), stop_event.set)

    sockets = ', '.join(str(sock.getsockname()) for sock in server.sockets or [])
    logging.info('proxy listening on %s -> %s:%s', sockets, args.target_host, args.target_port)
    async with server:
        serve_task = asyncio.create_task(server.serve_forever())
        await stop_event.wait()
        server.close()
        await server.wait_closed()
        serve_task.cancel()
        await asyncio.gather(serve_task, return_exceptions=True)
    logging.info('proxy stopped')


if __name__ == '__main__':
    asyncio.run(main())
