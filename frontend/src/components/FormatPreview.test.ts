import assert from 'node:assert/strict'
import { test } from 'node:test'
import { h } from 'vue'
import { format } from '../../test-support/fixtures.ts'
import { createVueHarness, deferred, flushPromises } from '../../test-support/vue.ts'

const segments = (value: string) => [{ type: 'static', config: { value }, order: 0 }]

function setup(context: any, values: Record<string, any>, previewFormat = async () => ({ data: { data: { preview: 'SAVED' } } })) {
  const harness = createVueHarness({ '@/api/formats': { formatsApi: { previewFormat } } }, {
    Date: class extends Date { constructor() { super('2026-11-07T12:00:00') } },
  })
  const view = harness.mount('@/components/format/FormatPreview.vue', values)
  context.after(view.unmount)
  return view
}

test('draft preview uses edited segments even when the format has already been saved', async context => {
  const view = setup(context, { formatId: 'format-a', segments: segments('EDITED'), draft: true })
  await view.state.fetchPreview()
  assert.equal(view.state.preview, 'EDITED')
})

test('read-only saved preview still uses the backend rendered number', async context => {
  const view = setup(context, { formatId: 'format-a', segments: segments('PLACEHOLDER') })
  await view.state.fetchPreview()
  assert.equal(view.state.preview, 'SAVED')
})

test('an old saved preview response cannot replace the current draft preview', async context => {
  const pending = deferred<any>()
  const view = setup(context, { formatId: 'format-a', segments: segments('OLD'), draft: false }, () => pending.promise)
  const savedPreview = view.state.fetchPreview()
  view.props.draft = true
  view.props.segments = segments('EDITED')
  await flushPromises()
  const draftPreview = view.state.fetchPreview()
  pending.resolve({ data: { data: { preview: 'SAVED' } } })
  await Promise.all([savedPreview, draftPreview])
  assert.equal(view.state.preview, 'EDITED')
  assert.equal(view.state.loading, false)
})

test('DDMMYYYY renders a concrete calendar date for unsaved formats', async context => {
  const view = setup(context, { segments: [{ type: 'date', config: { format: 'DDMMYYYY' }, order: 0 }] })
  await view.state.fetchPreview()
  assert.equal(view.state.preview, '07112026')
})

test('the format editor opts into draft previews for saved formats', async context => {
  const harness = createVueHarness({
    '@/components/format/FormatPreview.vue': {
      __esModule: true,
      default: { name: 'PreviewProbe', setup: (_props: any, { attrs }: any) => () => h('PreviewProbe', attrs) },
    },
    'vue-router': { useRouter: () => ({ push() {} }), useRoute: () => ({ params: { id: 'format-a' } }) },
    '@/stores/formats': { useFormatsStore: () => ({
      categories: [], segmentTypes: [], fetchCategories: async () => {}, fetchSegmentTypes: async () => {},
      fetchFormat: async () => ({ ...format(), segments_config: [] }),
    }) },
  })
  const view = harness.mount('@/views/FormatBuilderView.vue')
  context.after(view.unmount)
  await flushPromises()
  assert.equal(view.find('PreviewProbe')!.props.draft, true)
})

test('draft sequence preview follows the format start value and reacts to changes', async context => {
  const view = setup(context, {
    draft: true, sequenceStart: 100,
    segments: [{ type: 'sequence', config: { padding: 4, start: 1 }, order: 0 }],
  })
  await flushPromises()
  assert.equal(view.state.preview, '0100')
  view.props.sequenceStart = 250
  await flushPromises()
  assert.equal(view.state.preview, '0250')
})

test('yearly sequence preview respects the configured start and padding', async context => {
  const view = setup(context, {
    draft: true, sequenceStart: 75,
    segments: [{ type: 'yearly_sequence', config: { padding: 6 }, order: 0 }],
  })
  await flushPromises()
  assert.equal(view.state.preview, '000075')
})

test('the format editor supplies its start value to the preview', async context => {
  const harness = createVueHarness({
    '@/components/format/FormatPreview.vue': {
      __esModule: true,
      default: { props: ['sequenceStart'], setup: (props: any) => () => h('PreviewProbe', { sequenceStart: props.sequenceStart }) },
    },
    'vue-router': { useRouter: () => ({ push() {} }), useRoute: () => ({ params: { id: 'format-a' } }) },
    '@/stores/formats': { useFormatsStore: () => ({
      categories: [], segmentTypes: [], fetchCategories: async () => {}, fetchSegmentTypes: async () => {},
      fetchFormat: async () => ({ ...format(), sequence_start: 100, segments_config: [] }),
    }) },
  })
  const view = harness.mount('@/views/FormatBuilderView.vue')
  context.after(view.unmount)
  await flushPromises()
  assert.equal(view.find('PreviewProbe')!.props.sequenceStart, 100)
})
