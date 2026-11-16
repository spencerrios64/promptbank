# promptbank

Keep the prompts that worked. Pull them out of your AI chat history into a library you
can search, tag and copy from.

**Use it here: https://spencerrios64.github.io/promptbank/**

It is a single web page (`index.html`) with no dependencies and no server. Your files are
read in your browser and never uploaded. Works on desktop and on Android.

## Use

1. In each AI's settings, request a data export and download the file it sends you.
2. Open the page and pick the export files. Your own messages are listed, likely keepers
   first.
3. Press **Save to library** on the ones worth keeping, add tags, and use **Copy** whenever
   you need one. You can also add a prompt by hand.

## Good to know

- It can't tell which prompts gave good answers. It ranks by what it can see: prompts you
  sent more than once, prompts that opened a chat, and longer, detailed ones. You choose.
- The library is kept in this browser's storage on this device. **Back up** saves it as a
  `.json` file and **Restore** merges a backup in; clearing site data deletes the library.
- It reads export files. It cannot log in to your accounts or fetch chats by itself.
- **Claude** and **ChatGPT** exports are tested on small sample exports. **Gemini**, **Grok** and
  **DeepSeek** are read from their documented formats and have not been checked against real exports.
- Exports over 4 GB (zip64) aren't supported: unzip them and pick the `.json` inside.

Part of a family of small tools for AI chats: [chatvault](https://github.com/spencerrios64/chatvault), [chatzip](https://github.com/spencerrios64/chatzip), [chatrelay](https://github.com/spencerrios64/chatrelay), [chatbrief](https://github.com/spencerrios64/chatbrief), [chatscrub](https://github.com/spencerrios64/chatscrub), [chatcompare](https://github.com/spencerrios64/chatcompare), [chatstats](https://github.com/spencerrios64/chatstats) and [promptbank](https://github.com/spencerrios64/promptbank).
