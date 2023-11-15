# Documentation

Welcome to documentation d-draft 1 for this bot, we'll focus on all kinds of things, actually only one.

## Creating A Command

Let's say we need to create a command for random number generation, even though you could type "random number" into Google in the browser you are using right now to view this documentation.

Add an async function into the class named `randomCommand`, have it take an argument named `event` of type `EventInfo`.

Then use the `random.randint` function to generate a random number and `yield` it to make the bot send that message.

Success! You have created a new command!
