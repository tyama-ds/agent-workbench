"""Credential keyboard callbacks with synthetic events, not native OS IME evidence."""
import json

import pytest

from test_credential_recovery_frontend import check


@pytest.mark.parametrize('target', ['local', 'search'])
@pytest.mark.parametrize('flags', [
    {'isComposing': True, 'keyCode': 13},
    {'isComposing': True, 'keyCode': 229},
    # The final IME keydown can follow compositionend with isComposing false.
    {'isComposing': False, 'keyCode': 229},
])
def test_composition_enter_leaves_native_input_and_credential_state_alone(target, flags):
    check(r'''
await wire();const c=control(TARGET),text='  SYNTHETIC-にほん-未確定  ';
c.input.value=text;c.input.focus();const feedback=c.result.textContent,revision=ui.settingsRevision;
c.input.listeners.keydown({key:'Enter',...FLAGS,preventDefault(){throw Error('Composition canceled');}});
await flush();assert.equal(requests.length,0);assert.equal(c.input.value,text);
assert.equal(document.activeElement,c.input);assert.equal(c.result.textContent,feedback);
assert.equal(ui.credentialOperations.size,0);assert.equal(ui.settingsRevision,revision);
assert.equal(ui.configRevision,4);assert(!ui.settingsDirty&&!c.input.disabled&&!c.button.disabled);
'''.replace('TARGET', json.dumps(target)).replace('FLAGS', json.dumps(flags)))


@pytest.mark.parametrize('target', ['local', 'search'])
@pytest.mark.parametrize('activation', ['enter', 'button'])
def test_explicit_activation_after_composition_keeps_exact_request_and_one_flight(target, activation):
    activate = ("c.input.listeners.keydown({key:'Enter',isComposing:false,keyCode:13,preventDefault(){prevented++;}});"
                if activation == 'enter' else "void c.button.listeners.click();")
    check(r'''
await wire();const c=control(TARGET),text='  SYNTHETIC-確定  ';c.input.value=text;let prevented=0;
for(const flags of [{isComposing:true,keyCode:13},{isComposing:false,keyCode:229}]){
  c.input.listeners.keydown({key:'Enter',...flags,preventDefault(){throw Error('Composition canceled');}});
}
assert.equal(requests.length,0);assert.equal(c.input.value,text);
ACTIVATE
assert.equal(prevented,PREVENTED);assert.equal(requests.length,1);
assert.equal(requests[0].path,'/api/secrets');assert.equal(requests[0].options.method,'POST');
assert.deepEqual(requests[0].options.body,{id:TARGET,key:text,config_revision:4});
assert.equal(c.input.value,'');assert(c.input.disabled&&c.button.disabled);
c.input.listeners.keydown({key:'Enter',isComposing:false,keyCode:13,preventDefault(){}});
await c.button.listeners.click();assert.equal(requests.length,1);
accepted(0,TARGET);await flush();assert.equal(ui.credentialOperations.size,0);
assert.equal(requests.length,1);assert.equal(ui.configRevision,4);
assert(!c.input.disabled&&!c.button.disabled);assert(c.result.textContent.includes('有効性は未確認'));
'''.replace('TARGET', json.dumps(target)).replace('ACTIVATE', activate)
          .replace('PREVENTED', '1' if activation == 'enter' else '0'))


@pytest.mark.parametrize('target', ['local', 'search'])
@pytest.mark.parametrize('key', ['Process', 'Escape', 'Tab'])
def test_other_keys_do_not_set_credentials_or_cancel_native_behavior(target, key):
    check(r'''
await wire();const c=control(TARGET);c.input.value='SYNTHETIC-retained';
c.input.listeners.keydown({key:KEY,isComposing:false,keyCode:0,preventDefault(){throw Error('Other key canceled');}});
assert.equal(requests.length,0);assert.equal(c.input.value,'SYNTHETIC-retained');
'''.replace('TARGET', json.dumps(target)).replace('KEY', json.dumps(key)))


@pytest.mark.parametrize('target', ['local', 'search'])
@pytest.mark.parametrize('guard', [
    'ui.settingsDirty=true;', 'ui.configStale=true;', 'ui.authenticated=false;',
    'ui.settingsSaving=true;', 'ui.settingsReloading=true;',
])
def test_ordinary_enter_cannot_bypass_existing_credential_guards(target, guard):
    check(r'''
await wire();const c=control(TARGET);c.input.value='SYNTHETIC-retained';GUARD
let prevented=0;c.input.listeners.keydown({key:'Enter',isComposing:false,keyCode:13,preventDefault(){prevented++;}});
assert.equal(prevented,1);assert.equal(requests.length,0);assert.equal(c.input.value,'SYNTHETIC-retained');
assert.equal(ui.credentialOperations.size,0);assert.equal(ui.configRevision,4);
'''.replace('TARGET', json.dumps(target)).replace('GUARD', guard))
