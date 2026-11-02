# The dev stack's Emulators (docs/agents/dev-stack.md); the version here is the pin.
FROM node:24-slim
RUN npm install -g emulate@0.13.0
WORKDIR /emulate
ENTRYPOINT ["emulate"]
