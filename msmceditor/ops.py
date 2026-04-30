"""
Editing operations: block get/set, replace, fill, chunk delete/prune, save.

All mutating ops record undo snapshots via session.undo before changing chunks.
"""

import logging
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .java_world import parse_block_str
from .tasks import finish_task

log = logging.getLogger(__name__)


# ==================== Block get/set ====================

def get_block_info(session, x, y, z, dimension):
    """Get block info at coordinates."""
    try:
        block = session.world.get_block(x, y, z, dimension)
        if block is None:
            return {'error': 'Chunk not loaded', 'x': x, 'y': y, 'z': z}
        return {
            'block': block['name'],
            'properties': block.get('properties', {}),
            'blockEntity': None,
            'x': x, 'y': y, 'z': z,
            'dimension': dimension,
        }
    except Exception as e:
        return {'error': str(e), 'x': x, 'y': y, 'z': z}


def set_block(session, x, y, z, dimension, block_str):
    """Set a single block (with undo recording)."""
    try:
        name, props = parse_block_str(block_str)
        cx, cz = x >> 4, z >> 4

        session.undo.begin(session.world, dimension, f'Set block at {x},{y},{z}')
        try:
            session.undo.record_chunk(cx, cz)
            session.world.set_block(x, y, z, dimension, name, props)
            session.undo.commit()
        except Exception:
            session.undo.cancel()
            raise

        session.dirty = True
        return {'success': True, 'block': block_str, 'chunk': [cx, cz]}
    except Exception as e:
        log.error(f"set_block failed: {e}")
        return {'error': str(e)}


# ==================== Replace ====================

def run_replace(session, dimension, box, from_block_str, to_block_str,
                dry_run, task, emit_fn):
    """Replace blocks in a region. Runs in a background thread."""
    try:
        from_name, from_props = parse_block_str(from_block_str)
        to_name, to_props = parse_block_str(to_block_str)
        match_props = bool(from_props)

        x1, y1, z1 = box['x1'], box['y1'], box['z1']
        x2, y2, z2 = box['x2'], box['y2'], box['z2']
        x_lo, x_hi = sorted((x1, x2))
        y_lo, y_hi = sorted((y1, y2))
        z_lo, z_hi = sorted((z1, z2))

        total = (x_hi - x_lo + 1) * (y_hi - y_lo + 1) * (z_hi - z_lo + 1)
        task.total = total
        count = 0
        replaced = 0
        affected_chunks = set()
        op_label = f'Replace {from_name} -> {to_name}'

        if not dry_run:
            session.undo.begin(session.world, dimension, op_label)

        try:
            for cx_lo in range(x_lo >> 4, (x_hi >> 4) + 1):
                for cz_lo in range(z_lo >> 4, (z_hi >> 4) + 1):
                    if not dry_run:
                        session.undo.record_chunk(cx_lo, cz_lo)

            for x in range(x_lo, x_hi + 1):
                for z in range(z_lo, z_hi + 1):
                    for y in range(y_lo, y_hi + 1):
                        if task.cancelled:
                            if not dry_run:
                                session.undo.cancel()
                            task.result = {'replaced': replaced, 'cancelled': True}
                            finish_task(task.task_id)
                            return

                        count += 1
                        block = session.world.get_block(x, y, z, dimension)
                        if block is None:
                            continue
                        if block['name'] != from_name:
                            continue
                        if match_props:
                            actual = block.get('properties', {})
                            if any(actual.get(k) != v for k, v in from_props.items()):
                                continue

                        if not dry_run:
                            session.world.set_block(x, y, z, dimension, to_name, to_props)
                            affected_chunks.add((x >> 4, z >> 4))
                        replaced += 1

                        if count % 1000 == 0:
                            task.done = count
                            emit_fn('msmceditor:progress', {
                                'taskId': task.task_id,
                                'done': count, 'total': total,
                                'label': f'Replacing... {replaced} found'
                            })

            if dry_run:
                pass
            elif affected_chunks:
                session.dirty = True
                session.undo.commit()
                emit_fn('msmceditor:chunks-changed', {
                    'dim': dimension,
                    'chunks': list(affected_chunks),
                })
            else:
                session.undo.cancel()

            task.done = total
            task.result = {'replaced': replaced, 'dryRun': dry_run, 'cancelled': False}
            emit_fn('msmceditor:progress', {
                'taskId': task.task_id, 'done': total, 'total': total,
                'label': f'Done — {replaced} blocks {"would be " if dry_run else ""}replaced'
            })
        except Exception:
            if not dry_run:
                session.undo.cancel()
            raise
    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


# ==================== Fill ====================

def run_fill(session, dimension, box, block_str, task, emit_fn):
    """Fill a region with a single block."""
    try:
        name, props = parse_block_str(block_str)
        x1, y1, z1 = box['x1'], box['y1'], box['z1']
        x2, y2, z2 = box['x2'], box['y2'], box['z2']
        x_lo, x_hi = sorted((x1, x2))
        y_lo, y_hi = sorted((y1, y2))
        z_lo, z_hi = sorted((z1, z2))

        total = (x_hi - x_lo + 1) * (y_hi - y_lo + 1) * (z_hi - z_lo + 1)
        task.total = total
        count = 0
        affected = set()

        session.undo.begin(session.world, dimension, f'Fill {block_str}')
        try:
            for cx in range(x_lo >> 4, (x_hi >> 4) + 1):
                for cz in range(z_lo >> 4, (z_hi >> 4) + 1):
                    session.undo.record_chunk(cx, cz)

            for x in range(x_lo, x_hi + 1):
                for z in range(z_lo, z_hi + 1):
                    for y in range(y_lo, y_hi + 1):
                        if task.cancelled:
                            session.undo.cancel()
                            task.result = {'filled': count, 'cancelled': True}
                            finish_task(task.task_id)
                            return
                        try:
                            session.world.set_block(x, y, z, dimension, name, props)
                            affected.add((x >> 4, z >> 4))
                            count += 1
                        except KeyError:
                            pass
                        if count % 1000 == 0:
                            task.done = count
                            emit_fn('msmceditor:progress', {
                                'taskId': task.task_id, 'done': count, 'total': total,
                                'label': f'Filling... {count}/{total}'
                            })

            session.dirty = True
            session.undo.commit()
            emit_fn('msmceditor:chunks-changed', {
                'dim': dimension, 'chunks': list(affected)
            })
            task.done = total
            task.result = {'filled': count, 'cancelled': False}
            emit_fn('msmceditor:progress', {
                'taskId': task.task_id, 'done': total, 'total': total,
                'label': f'Done — filled {count} blocks'
            })
        except Exception:
            session.undo.cancel()
            raise
    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


# ==================== Chunk operations ====================

def delete_chunks(session, dimension, coords, task, emit_fn):
    """Delete specified chunks. Records undo snapshots first."""
    task.total = len(coords)
    try:
        session.undo.begin(session.world, dimension, f'Delete {len(coords)} chunks')
        try:
            for (cx, cz) in coords:
                session.undo.record_chunk(cx, cz)

            for i, (cx, cz) in enumerate(coords):
                if task.cancelled:
                    session.undo.cancel()
                    break
                try:
                    session.world.delete_chunk(cx, cz, dimension)
                except Exception:
                    pass
                task.done = i + 1
                if (i + 1) % 10 == 0:
                    emit_fn('msmceditor:progress', {
                        'taskId': task.task_id, 'done': i + 1, 'total': len(coords),
                        'label': f'Deleting chunks... {i + 1}/{len(coords)}'
                    })

            session.dirty = True
            if not task.cancelled:
                session.undo.commit()
            emit_fn('msmceditor:chunks-changed', {'dim': dimension, 'chunks': coords})
            task.result = {'deleted': task.done, 'cancelled': task.cancelled}
            emit_fn('msmceditor:progress', {
                'taskId': task.task_id, 'done': task.done, 'total': len(coords),
                'label': f'Done — {task.done} chunks deleted'
            })
        except Exception:
            session.undo.cancel()
            raise
    except Exception as e:
        task.error = str(e)
        emit_fn('msmceditor:error', {'message': str(e)})
    finally:
        finish_task(task.task_id)


def prune_chunks(session, dimension, keep_box, task, emit_fn):
    """Delete all chunks OUTSIDE keep_box (in chunk coords)."""
    all_chunks = session.world.all_chunk_coords(dimension)
    x1 = min(keep_box['x1'], keep_box['x2'])
    z1 = min(keep_box['z1'], keep_box['z2'])
    x2 = max(keep_box['x1'], keep_box['x2'])
    z2 = max(keep_box['z1'], keep_box['z2'])

    to_delete = [(cx, cz) for cx, cz in all_chunks
                 if not (x1 <= cx <= x2 and z1 <= cz <= z2)]
    delete_chunks(session, dimension, to_delete, task, emit_fn)


# ==================== Save ====================

def save_world(session, backup_dir):
    """Save the world. Creates an auto-backup zip first."""
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"auto-pre-edit-{ts}.zip"
        backup_path = Path(backup_dir) / backup_name
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in session.world_path.rglob('*'):
                if f.is_file():
                    if '.msmceditor-cache' in str(f):
                        continue
                    arc = f.relative_to(session.world_path.parent)
                    zf.write(f, arc)

        session.world.save()
        session.dirty = False
        return True, f"Saved successfully (backup: {backup_name})"
    except Exception as e:
        log.error(f"Failed to save world: {e}")
        return False, str(e)
