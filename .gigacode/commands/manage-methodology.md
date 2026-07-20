---
description: Создать или обновить системную МНТ через обнаружение рабочего пространства, сверку доказательств, проверку качества, точный diff и явное локальное подтверждение.
---

Delegate to the `manage-methodology` skill with the requested `create`,
`update-local`, or `publish` mode. `create` and `update-local` always recollect
every confirmed repository and Confluence source. It never skips approval: it must
show and receive explicit approval for the exact `workspace-manifest` patch before
applying it, and later for the exact `methodology-patch` before applying it.
`publish` is a separate approval after showing the exact Confluence diff; it uses
the previously confirmed fixed page ID and delegates the one update to
`mnt-confluence-publisher`. If the host page capabilities are unavailable, return
`blocked` without a Confluence update.


`mnt-validator` is read-only and returns an inline `accept|blocked` envelope. It
references only pre-existing quality-report, descriptor, and source-map artifacts;
it never creates a validator report.


It checks pre-existing artifact content and declarations only; it does not recompute
hashes or bytes. The deterministic apply engine performs that revalidation
immediately before installation.


Immediately after authoring, the workflow prepares one exact methodology patch and
descriptor. The quality gate, validator, review, approval, and apply operations
reuse that same unchanged methodology patch and descriptor; it is not regenerated.
