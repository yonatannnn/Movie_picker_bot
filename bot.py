import os
import random
from datetime import datetime
from telethon import TelegramClient, events
from pymongo import MongoClient
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

# MongoDB setup
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["movie_bot"]
groups_collection = db["groups"]
users_collection = db["users"]
movies_collection = db["movies"]

# Telethon setup
api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

# Helper functions
def generate_group_id():
    return str(random.randint(100000, 999999))

async def send_movie_to_group(group_id):
    group = groups_collection.find_one({"group_id": group_id})
    if not group:
        return

    movies = list(movies_collection.find({"group_id": group_id}))
    if not movies:
        return

    movie = random.choice(movies)
    movie_link = movie["movie_link"]

    # Send the movie to each member of the group individually
    for member_id in group["members"]:
        try:
            await client.send_message(member_id, f"🎬 This week's movie: {movie_link}")
        except Exception as e:
            print(f"Failed to send movie to user {member_id}: {e}")

    # Remove the movie from the database
    movies_collection.delete_one({"_id": movie["_id"]})

# Commands
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply(
        "Welcome to the Movie Bot! 🎬\n\n"
        "Here are the commands you can use:\n"
        "/create group_name - Create a new group\n"
        "/join group_id - Join a group\n"
        "/add group_id movie_link - Add a movie to a group\n"
        "/delete movie_link - Delete a movie from your groups\n"
        "/groups - List all your groups\n"
        "/remaining_movies group_id - Show remaining movies in a group\n"
    )

@client.on(events.NewMessage(pattern='/create'))
async def create_group(event):
    group_name = event.message.text.split(maxsplit=1)[1]
    group_id = generate_group_id()
    groups_collection.insert_one({
        "group_name": group_name,
        "group_id": group_id,
        "chat_id": event.chat_id,
        "members": [event.sender_id]
    })
    await event.reply(f"Group '{group_name}' created with ID: {group_id}")

@client.on(events.NewMessage(pattern='/join'))
async def join_group(event):
    group_id = event.message.text.split(maxsplit=1)[1]
    group = groups_collection.find_one({"group_id": group_id})
    if not group:
        await event.reply("Group not found.")
        return

    if event.sender_id in group["members"]:
        await event.reply("You are already in this group.")
        return

    groups_collection.update_one(
        {"group_id": group_id},
        {"$push": {"members": event.sender_id}}
    )
    await event.reply(f"You have joined the group: {group['group_name']}")

@client.on(events.NewMessage(pattern='/add'))
async def add_movie(event):
    parts = event.message.text.split(maxsplit=2)
    if len(parts) < 3:
        await event.reply("Usage: /add group_id movie_link")
        return

    group_id, movie_link = parts[1], parts[2]
    group = groups_collection.find_one({"group_id": group_id})
    if not group:
        await event.reply("Group not found.")
        return

    # Check if the user is a member of the group
    if event.sender_id not in group["members"]:
        await event.reply("You are not a member of this group. Join the group first.")
        return

    # Check if the movie already exists in the group
    existing_movie = movies_collection.find_one({"group_id": group_id, "movie_link": movie_link})
    if existing_movie:
        await event.reply("This movie already exists in the group.")
        return

    movies_collection.insert_one({
        "group_id": group_id,
        "movie_link": movie_link
    })
    await event.reply(f"Movie added to group: {group['group_name']}")



@client.on(events.NewMessage(pattern='/groups'))
async def list_groups(event):
    user_groups = groups_collection.find({"members": event.sender_id})
    if not user_groups:
        await event.reply("You are not in any groups.")
        return

    group_list = "\n".join([f"{group['group_name']} (ID: {group['group_id']})" for group in user_groups])
    await event.reply(f"Your groups:\n{group_list}")

@client.on(events.NewMessage(pattern='/remaining_movies'))
async def remaining_movies(event):
    parts = event.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await event.reply("Usage: /remaining_movies group_id")
        return

    group_id = parts[1]
    group = groups_collection.find_one({"group_id": group_id})
    if not group:
        await event.reply("Group not found.")
        return

    movies = list(movies_collection.find({"group_id": group_id}))
    if not movies:
        await event.reply("No movies remaining in this group.")
        return

    movie_list = "\n".join([f"{i+1}. {movie['movie_link']}" for i, movie in enumerate(movies)])
    await event.reply(f"Remaining movies in group '{group['group_name']}':\n{movie_list}")

@client.on(events.NewMessage(pattern='/delete'))
async def delete_movie(event):
    parts = event.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await event.reply("Usage: /delete movie_link")
        return

    movie_link = parts[1]

    # Find the group(s) the user is a member of
    user_groups = groups_collection.find({"members": event.sender_id})
    if not user_groups:
        await event.reply("You are not a member of any groups.")
        return

    # Check if the movie exists in any of the user's groups
    movie_deleted = False
    for group in user_groups:
        movie = movies_collection.find_one({"group_id": group["group_id"], "movie_link": movie_link})
        if movie:
            movies_collection.delete_one({"_id": movie["_id"]})
            movie_deleted = True
            await event.reply(f"Movie deleted from group: {group['group_name']}")
            break

    if not movie_deleted:
        await event.reply("Movie not found in any of your groups.")

# Schedule weekly movie sending
async def schedule_movie_sending():
    while True:
        now = datetime.now()
        if now.weekday() == 0 and now.hour == 3 and now.minute == 0:  # Monday at 8:00 AM
            print(now.weekday(), now.hour, now.minute)
            groups = groups_collection.find()
            for group in groups:
                await send_movie_to_group(group["group_id"])
            await asyncio.sleep(60)  # Avoid multiple triggers in the same minute
        await asyncio.sleep(30)  # Check every 30 seconds

# Start the bot
print("Bot is running...")
client.loop.run_until_complete(schedule_movie_sending())
client.run_until_disconnected()