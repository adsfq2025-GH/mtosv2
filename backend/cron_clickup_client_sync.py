import asyncio

import clickup_client_sync


async def main() -> None:
    res = await clickup_client_sync.sync_all_tenants()
    print(res)


if __name__ == "__main__":
    asyncio.run(main())

