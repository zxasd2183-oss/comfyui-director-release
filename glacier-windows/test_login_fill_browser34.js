// Pure DOM mock: run the exact Glacier fill code in a sandbox without a browser,
// internet, credentials, Qt or arbitrary page-script execution.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync(0, 'utf8');
function scenario({host='github.com', protocol='https:', port='', frame=false,
                   loading=false, hidden=false, withPassword=true,
                   withUsername=true, otherForm=false}={}) {
  let submits=0;
  class Input {}
  Object.defineProperty(Input.prototype,'value', {
    get() {return this._value||'';},
    set(v){this._value=v;}
  });
  const make=(type,name,form,vis=true) => {
    const element=Object.create(Input.prototype);
    Object.assign(element,{type,name,id:name,autocomplete:'',
      isConnected:true,disabled:false,readOnly:false,form,
      getClientRects:()=>vis?[{}]:[],
      getAttribute:()=>'',dispatchEvent:()=>true});
    return element;
  };
  const form={querySelectorAll:()=>inputs.filter(x=>x.form===form),
    submit:()=>{submits++},requestSubmit:()=>{submits++}};
  const alt={querySelectorAll:()=>inputs.filter(x=>x.form===alt),
    submit:()=>{submits++}};
  const inputs=[];
  const user=withUsername?make('email','email',form):null;
  if(user)inputs.push(user);
  const password=withPassword?make('password','password',form,!hidden):null;
  if(password)inputs.push(password);
  const unrelated=otherForm?make('password','other',alt):null;
  if(unrelated)inputs.push(unrelated);
  const win={};
  win.top=frame?{}:win;
  win.getComputedStyle=()=>({display:'block',visibility:'visible',opacity:'1'});
  const document={
    readyState:loading?'loading':'complete',
    activeElement:null,
    querySelectorAll:()=>inputs,
  };
  const context={
    location:{hostname:host,protocol,port},
    document,window:win,HTMLInputElement:Input,
    Event: class Event {constructor(type,opts){this.type=type;this.bubbles=opts.bubbles}},
    Object,Number,Array,String,
  };
  const result=vm.runInNewContext(code,context,{timeout:1000});
  return {result,user:user?user.value:null,
    password:password?password.value:null,
    unrelated:unrelated?unrelated.value:null,
    submits};
}
let s=scenario();
assert.equal(s.result,'filled');
assert.equal(s.user,'susan@example.invalid');
assert.equal(s.password,'example-secret-34');
assert.equal(s.submits,0);
s=scenario({host:'evilgithub.com'});assert.equal(s.result,'refused');
assert.equal(s.user,'');assert.equal(s.password,'');
s=scenario({host:'github.com.evil.test'});assert.equal(s.result,'refused');
s=scenario({host:'auth.github.com'});assert.equal(s.result,'refused');
s=scenario({host:'www.github.com'});assert.equal(s.result,'filled');
s=scenario({protocol:'http:'});assert.equal(s.result,'refused');
s=scenario({port:'444'});assert.equal(s.result,'refused');
s=scenario({frame:true});assert.equal(s.result,'refused');
s=scenario({loading:true});assert.equal(s.result,'refused');
s=scenario({withPassword:false});assert.equal(s.result,'username-only');
s=scenario({hidden:true});assert.equal(s.result,'username-only');
s=scenario({withUsername:false});assert.equal(s.result,'password-only');
s=scenario({withUsername:false,withPassword:false});assert.equal(s.result,'no-fields');
s=scenario({otherForm:true});assert.equal(s.result,'filled');
assert.equal(s.unrelated,'');assert.equal(s.submits,0);
console.log('PASS: HTTPS exact host, iframe, hidden field, user intent and no-submit guards');
