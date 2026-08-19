import asyncio, websockets


CONVERSATION_ID = "5c96fa84-3647-4e41-bd82-846298288c9e"
PARTICIPANT_ID = "13bdf94a-9391-4eb7-9c31-7efaf509063d"
PARTICIPANT_TOKEN = "yqiTWAML301YpI470SvZa5M-8vSsR8Rb0C1TpmAlVa0"


async def main():

    url = (
        f"ws://127.0.0.1:8000/ws/{CONVERSATION_ID}"
        f"?participant_id={PARTICIPANT_ID}"
        f"&token={PARTICIPANT_TOKEN}"
    )

    try:
        async with websockets.connect(url) as websocket:

            print("Connected!")

            await websocket.send("Hello from Python")

            print("Message sent!")

            while True:
                message = await websocket.recv()
                print("Received:", message)

    except websockets.ConnectionClosed as e:
        print("Connection closed")
        print("Code:", e.code)
        print("Reason:", e.reason)

    except Exception as e:
        print("Client error:", repr(e))


asyncio.run(main())