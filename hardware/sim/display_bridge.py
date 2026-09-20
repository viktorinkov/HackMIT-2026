"""Seeed-to-BOX-3 display mock or explicit USB-to-TCP development bridge.

python3 hardware/sim/display_bridge.py --mock
python3 hardware/sim/display_bridge.py --serial /dev/cu.usbmodem101
Emulator endpoint: 10.0.2.2:9001. Binds localhost; never sends motor commands.
"""
import argparse
import asyncio
import json


def state(hello=True):
    return (json.dumps({'display': 'peel', 'text': 'Hello!' if hello else 'Peel',
                        'version': 1, 'via': 'seeed-radio'}) + '\n').encode()


async def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--mock', action='store_true')
    mode.add_argument('--serial')
    parser.add_argument('--port', type=int, default=9001)
    args = parser.parse_args()
    port = None
    if args.serial:
        import serial
        from serial.tools import list_ports
        device = next((p for p in list_ports.comports() if p.device == args.serial), None)
        if not device or (device.serial_number or '').upper() != '68:EE:8F:50:27:E8':
            raise SystemExit('Use the Seeed USB port (68:EE:8F:50:27:E8), not the BOX-3.')
        port = serial.Serial(args.serial, 115200, timeout=0.2)
    active = False

    async def client(reader, writer):
        nonlocal active
        if active:
            writer.close()
            await writer.wait_closed()
            return
        active = True
        print('display client connected', flush=True)
        async def telemetry():
            if not port:
                return
            while True:
                raw = await asyncio.to_thread(port.readline)
                if raw:
                    print('USB display:', raw.decode(errors='replace').strip(), flush=True)
                    writer.write(raw)
                    await writer.drain()
        task = asyncio.create_task(telemetry())
        try:
            if not port:
                writer.write(b'{"displayRelay":2,"t":-1,"trans":200,"scat":40,"tC":null}\n')
                await writer.drain()
            while raw := await reader.readline():
                # Session may request diagnostics with an unframed d before a
                # display line. Ignore that read-only request in this display mock.
                command = raw.strip().lstrip(b'd')
                phase = len(command) == 6 and command[:5] == b'PHASE' and command[5:6] in b'01234567'
                if command not in (b'HELLO', b'PEEL') and not phase:
                    writer.write(b'{"error":"Unknown display command"}\n')
                elif port:
                    await asyncio.to_thread(port.write, command + b'\n')
                else:
                    print('mock display:', command.decode(), flush=True)
                    if phase:
                        writer.write((json.dumps({'display':'peel','scene':2+int(command[-1:]),'version':1,'via':'seeed-radio'})+'\n').encode())
                    else:
                        writer.write(state(command == b'HELLO'))
                await writer.drain()
        except (ConnectionError, ValueError):
            pass
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            active = False
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            print('display client disconnected', flush=True)
    server = await asyncio.start_server(client, '127.0.0.1', args.port, limit=1024)
    print(f'display {"mock" if args.mock else "USB bridge"} at 127.0.0.1:{args.port}', flush=True)
    try:
        async with server:
            await server.serve_forever()
    finally:
        if port:
            port.close()

if __name__ == '__main__':
    asyncio.run(main())
