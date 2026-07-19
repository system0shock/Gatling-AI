---
description: Создать или обновить системную МНТ через обнаружение рабочего пространства, сверку доказательств, проверку качества, точный diff и явное локальное подтверждение.
---

Delegate to the `manage-methodology` skill with the requested `create` or
`update-local` mode. It never skips approval: it must show and receive explicit
approval for the exact `workspace-manifest` patch before applying it, and later
for the exact `methodology-patch` before applying it. Do not publish to Confluence.
