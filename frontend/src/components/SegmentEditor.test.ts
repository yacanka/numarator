import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createVueHarness } from '../../test-support/vue.ts'

function flatten(node: any): any[] {
  return [node, ...node.children.flatMap(flatten)]
}

for (const type of ['sequence', 'yearly_sequence']) {
  test(`${type} editor directs start and step changes to format settings while preserving existing JSON`, context => {
    const updates: any[] = []
    const harness = createVueHarness()
    const view = harness.mount('@/components/format/SegmentEditor.vue', {
      segment: { type, config: { padding: 4, start: 100, step: 5 }, order: 0, label: 'Sequence' },
      onUpdate: (segment: any) => updates.push(segment),
    })
    context.after(view.unmount)
    const nodes = flatten(view.find('NForm'))
    assert.equal(nodes.filter(node => node.type === 'NInputNumber').length, 1)
    assert.ok(nodes.map(node => node.text || '').join(' ').includes('Sıra Numarası Ayarları'))
    view.state.localSegment.config.padding = 6
    view.state.handleSave()
    assert.equal(updates.length, 1)
    assert.deepEqual({ ...updates[0].config }, { padding: 6, start: 100, step: 5 })
  })
}
