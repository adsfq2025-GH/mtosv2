import asyncio
import os

import monthly_touch


async def main() -> None:
    model = os.environ.get("MONTHLY_TOUCH_MODEL") or None
    extra_context = os.environ.get("MONTHLY_TOUCH_EXTRA_CONTEXT") or None
    res = await monthly_touch.generate_for_all(model_key=model, extra_context=extra_context)
    print(res)


if __name__ == "__main__":
    asyncio.run(main())

