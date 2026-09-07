const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  const source = fs.readFileSync(path.join(__dirname, '../medusahc_control/web/app.js'), 'utf8');
  const input = {value: '10', dataset: {settingInput: 't0_prime_amount'}};
  const view = {id: 'view-tuning', contains: () => false};
  const context = {
    app: {settings: {values: {t0_prime_amount: 10}}},
    document: {activeElement: null},
    $: selector => selector === '.view.active' ? view : null,
    $$: () => [input],
    api: async () => ({values: {t0_prime_amount: 20}}),
    renderSettings: payload => { context.rendered = payload; input.value = String(payload.values.t0_prime_amount); },
    toast: () => {},
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function settingsRefreshAllowed()'), source.indexOf('function renderSettings(')), context);
  return {context, input, view};
}

test('background refresh updates idle settings', async () => {
  const {context, input} = fixture();
  await context.loadSettings({background: true});
  assert.equal(input.value, '20');
});

test('background refresh preserves unsent edits', async () => {
  const {context, input} = fixture();
  input.value = '30';
  await context.loadSettings({background: true});
  assert.equal(input.value, '30');
  assert.equal(context.rendered, undefined);
});

test('edits made during a request are also preserved', async () => {
  const {context, input} = fixture();
  context.api = async () => { input.value = '40'; return {values: {t0_prime_amount: 20}}; };
  await context.loadSettings({background: true});
  assert.equal(input.value, '40');
  assert.equal(context.rendered, undefined);
});

test('refresh skips focused inputs and inactive settings views', async () => {
  const {context, view} = fixture();
  context.document.activeElement = {matches: () => true};
  view.contains = () => true;
  await context.loadSettings({background: true});
  assert.equal(context.rendered, undefined);
  view.contains = () => false;
  view.id = 'view-overview';
  await context.loadSettings({background: true});
  assert.equal(context.rendered, undefined);
});
