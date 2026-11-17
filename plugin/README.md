# promptbank plugin

Keep the prompts that worked: find them in your AI chat history and save, tag and search them in a library.

## What you can ask

- "Find the prompts I reused the most" (attach your exports)
- "Save prompts 2 and 5 with the tag roblox"
- "Show my saved prompts about code review"

## What it can't do

It cannot tell which prompts gave good answers. It ranks what it can see (prompts you reused, prompts that opened a chat, longer ones) and you choose what to keep. The library is a JSON file in the folder Claude works in; ask Claude to hand it back to you after changes so it is not lost.

Project: https://github.com/spencerrios64/promptbank

## Install

In Claude Code:

```
/plugin marketplace add spencerrios64/promptbank
/plugin install promptbank@promptbank
```

In the Claude app, download the `plugin` folder as a zip, rename it to `.plugin` and open it in a chat.
