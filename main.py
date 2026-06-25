from botson import BotApp

app = BotApp()

app.command("start", "Hello!")

async def echo(m):
    try:
        await m.send_copy(chat_id=m.chat.id)
    except TypeError:
        await m.answer("Nice try!")

app.any(echo)

app.run()
