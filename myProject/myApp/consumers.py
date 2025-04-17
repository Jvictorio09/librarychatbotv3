from channels.generic.websocket import AsyncWebsocketConsumer
import json

class LibrarianConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("librarian_notify", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("librarian_notify", self.channel_name)

    async def notify_upload_complete(self, event):
        await self.send(text_data=json.dumps({
            "message": event["message"]
        }))
