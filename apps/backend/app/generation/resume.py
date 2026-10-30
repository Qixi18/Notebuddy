"""Validated model composition checkpoints; no business body is stored here."""
from __future__ import annotations

from dataclasses import asdict

from app.document_processing.checkpoints import fingerprint, get_step, put_step
from app.generation.composer import Composition, CompositionError, compose
from app.notes.document import normalize_document, validate_document


def compose_batch(db, scope, snapshot, plan, batch, generator, *, compose_impl=None):
    identity = fingerprint([snapshot, plan, batch, generator, 'composition-v1'])
    key = fingerprint(batch)
    cached = get_step(db, scope, 'compose', key, identity)
    if cached is not None:
        return Composition(**cached)
    db.commit()
    result = (compose_impl or compose)(snapshot, plan, batch, generator=generator)
    document = validate_document(normalize_document({'type': 'doc', 'content': result.nodes}))
    allowed = {block['block_id'] for source in snapshot.get('sources', [])
               for section in source['sections'] for block in section['blocks']}
    if any(identity not in allowed for ids in result.source_map.values() for identity in ids):
        raise CompositionError('生成批次包含输入之外的来源', code='invalid_sources')
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
    namespace(result.nodes)
    result.source_map = {aliases.get(key, key): ids for key, ids in result.source_map.items()}
    put_step(db, scope, 'compose', key, identity, asdict(result))
    return result
