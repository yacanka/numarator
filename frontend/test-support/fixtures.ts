export function format(id = 'format-a', code = 'FORMAT_A') {
  return {
    id, code, name: code, description: '', status: 'active', category: null,
    segments_config: [{ type: 'context', config: { key: 'department', default: 'GEN' }, order: 0 }],
    sequence_reset_period: 'never', sequence_start: 1, sequence_step: 1,
    validation_regex: '', example_output: '', total_generated: 0, preview: 'GEN0001',
    tags: [], created_at: '2026-11-07T12:00:00Z', updated_at: '2026-11-07T12:00:00Z',
  }
}

export function document(id = 'document-a', number = 'DOC-0001') {
  return {
    id, document_number: number, format: 'format-a', format_code: 'FORMAT_A', format_name: 'Format A',
    status: 'active', sequence_value: 1, context_data: {}, metadata: {}, external_reference: '',
    generated_by: 1, generated_by_username: 'test-user', generated_at: '2026-11-07T12:00:00Z',
    used_at: null, cancelled_at: null, cancellation_reason: '',
  }
}
