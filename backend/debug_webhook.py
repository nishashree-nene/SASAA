import asyncio, httpx

async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post(
            'http://localhost:8001/api/v1/telephony/webhooks/mock',
            data={'CallSid':'abc123','From':'+91987','To':'+91123','CallStatus':'no-answer'}
        )
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text[:500]}")

asyncio.run(main())
