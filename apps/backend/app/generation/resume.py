"""Validated model composition checkpoints; no business body is stored here."""
from __future__ import annotations

from dataclasses import asdict

from app.document_processing.checkpoints import fingerprint, get_step, put_step
from app.generation.composer import Composition, CompositionError, compose
from app.generation.quality_gate import inspect_generated_math
from app.notes.document import DocumentValidationError, normalize_document, validate_document


def compose_batch(db, scope, snapshot, plan, batch, generator, *, compose_impl=None,
                  allow_uncached_invalid=False):
    identity = fingerprint([snapshot, plan, batch, generator, 'composition-v2-draft-v1'])
    key = fingerprint(batch)
    cached = get_step(db, scope, 'compose', key, identity)
    if cached is not None:
        return Composition(**cached)
    db.commit()
    result = (compose_impl or compose)(snapshot, plan, batch, generator=generator)
    allowed = {block['block_id'] for source in snapshot.get('sources', [])
               for section in source['sections'] for block in section['blocks']}
    if any(identity not in allowed for ids in result.source_map.values() for identity in ids):
        raise CompositionError('生成批次包含输入之外的来源', code='invalid_sources')
    try:
        document = validate_document(normalize_document({'type': 'doc', 'content': result.nodes}))
        ids = {(node.get('attrs') or {}).get('blockId') for node in document['content']}
        if None in ids or ids != set(result.source_map) or any(not v for v in result.source_map.values()):
            raise CompositionError('生成批次的来源覆盖不完整', code='missing_sources')
        if not inspect_generated_math(document).passed:
            raise DocumentValidationError('生成批次公式需要校验')
    except (DocumentValidationError, CompositionError):
        if allow_uncached_invalid:
            # Preserve the standard worker's existing final format-repair gate,
            # but never cache an invalid fragment as a successful paid step.
            return result
        raise
    result.nodes = document['content']
    aliases = {}
    def namespace(nodes):
        for node in nodes:
            attrs = node.get('attrs') or {}
            old = attrs.get('blockId')
            if isinstance(old, str):
                aliases[old] = 'ai-' + fingerprint([scope, identity, old])[:24]
                attrs['blockId'] = aliases[old]
            namespace(node.get('content') or [])
    if not allow_uncached_invalid:
        namespace(result.nodes)
    result.source_map = {aliases.get(key, key): ids for key, ids in result.source_map.items()}
    put_step(db, scope, 'compose', key, identity, asdict(result))
    return result
