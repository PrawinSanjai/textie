import asyncio, json, os, websockets


CONVERSATION_ID = "5c96fa84-3647-4e41-bd82-846298288c9e"
PARTICIPANT_ID = os.environ["TEXTIE_PARTICIPANT_ID"]
PARTICIPANT_TOKEN = os.environ["TEXTIE_PARTICIPANT_TOKEN"]


async def main():

    url = f"ws://127.0.0.1:8000/ws/{CONVERSATION_ID}"

    try:
        async with websockets.connect(url) as websocket:
            await websocket.send(json.dumps({
                "type": "authenticate",
                "participant_id": PARTICIPANT_ID,
                "participant_token": PARTICIPANT_TOKEN,
            }))

            print("Connected!")

            await websocket.send(json.dumps({"type": "message", "client_message_id": "73d809dc-628a-4f46-89b1-aafbc37e7e89", "message": "Hello from Python"}))

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
