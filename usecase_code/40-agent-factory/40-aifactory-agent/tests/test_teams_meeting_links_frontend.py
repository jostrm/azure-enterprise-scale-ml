from test_teams_meeting_frontend import HARNESS, STATIC
from test_voice_frontend import node


CHAT = HARNESS + r"""
const thread = "19:approved-meeting@thread.v2";
issued.chat_enabled = true; issued.chat_thread_id = thread;
const fetchBase = env.fetch;
let previewCount=0, sendCount=0, previewStatus=200, sendStatus=200, previewRelease=null, sendRelease=null;
let previewBodyRelease=null, sendBodyRelease=null;
env.AbortController=AbortController;
const draft = {draft_id:"draft-one", voice_generation:0, thread_id:thread,
  content:"ESAF Agent Chat sources:\nhttps://learn.microsoft.com/azure/",
  links:[{title:"Source 1",url:"https://learn.microsoft.com/azure/"}],
  expires_at:(now+60000)/1000};
env.fetch=async (url, options) => {
  if(url.endsWith("/links/preview")){
    requests.push({url,options});previewCount++;
    if(previewRelease)await new Promise(resolve=>{previewRelease=resolve;});
    return {ok:previewStatus===200,status:previewStatus,json:async()=>{
      if(previewBodyRelease)await new Promise(resolve=>{previewBodyRelease=resolve;});
      return draft;
    }};
  }
  if(url.endsWith("/links/send")){
    requests.push({url,options});sendCount++;
    if(sendRelease)await new Promise(resolve=>{sendRelease=resolve;});
    return {ok:sendStatus===200,status:sendStatus,
      json:async()=>{
        if(sendBodyRelease)await new Promise(resolve=>{sendBodyRelease=resolve;});
        return sendStatus===200?{status:"sent",message_id:"message-one",thread_id:thread}:{detail:{code:"delivery_unknown"}};
      }};
  }
  return fetchBase(url,options);
};
async function ready(){
  await join(); agents[0].call.info={threadId:thread};
  sockets[0].open();sockets[0].receive({type:"ready"});
}
function offer(id="offer-one"){
  sockets[0].receive({type:"answer",chat_links:{offer_id:id,count:1}});
}
"""


def test_answer_offers_links_but_never_posts_or_previews_automatically():
    node(CHAT + r"""
(async()=>{
 await ready();offer();
 assert.equal(previewCount,0);assert.equal(sendCount,0);
 assert.equal(client.linkState.state,"available");
 const value=await client.previewLinks();
 assert.equal(previewCount,1);assert.equal(sendCount,0);
 assert.equal(client.linkState.state,"preview");
 assert.equal(value.content,draft.content);assert.equal(value.thread_id,thread);
 const body=JSON.parse(requests.at(-1).options.body);
 assert.deepEqual(body,{voice_generation:0,offer_id:"offer-one",thread_id:thread});
 await client.postLinks({confirmed:false});assert.equal(sendCount,0);
 assert.equal(client.linkState.state,"preview");
 await client.postLinks({confirmed:true});
 assert.equal(sendCount,1);assert.equal(client.linkState.state,"sent");
 assert.equal(client.linkState.message_id,"message-one");
 assert.deepEqual(JSON.parse(requests.at(-1).options.body),
   {voice_generation:0,draft_id:"draft-one",thread_id:thread,confirmed:true});
 await client.postLinks({confirmed:true});assert.equal(sendCount,1);
 assert.ok(!requests.some(r=>r.url.includes("graph.microsoft")||r.url.includes("communication.azure")));
 await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_wrong_thread_or_disabled_chat_cannot_preview_or_send_but_voice_continues():
    node(CHAT + r"""
(async()=>{
 await ready();agents[0].call.info.threadId="19:other@thread.v2";offer();
 await client.previewLinks();await client.postLinks({confirmed:true});
 assert.equal(previewCount,0);assert.equal(sendCount,0);assert.equal(client.phase,"listening");
 assert.ok(!agents[0].call.hungUp);
 issued.chat_enabled=false;await client.stop();await join();
 agents[1].call.info={threadId:thread};sockets[1].open();sockets[1].receive({type:"ready"});
 sockets[1].receive({type:"answer",chat_links:{offer_id:"offer",count:1}});
 await client.previewLinks();assert.equal(previewCount,0);
 await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_late_preview_does_not_survive_new_answer_or_leave():
    node(CHAT + r"""
(async()=>{
 await ready();offer();previewRelease=true;
 const pending=client.previewLinks();for(let i=0;i<4;i++)await tick();
 offer("new-offer");previewRelease();await pending;
 assert.notEqual(client.linkState.state,"preview");
 await client.postLinks({confirmed:true});assert.equal(sendCount,0);
 previewRelease=true;
 const late=client.previewLinks();for(let i=0;i<4;i++)await tick();
 await client.stop();previewRelease();await late;
 assert.equal(client.linkState.state,"unavailable");assert.equal(sendCount,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_send_is_single_flight_and_unknown_delivery_is_not_retried():
    node(CHAT + r"""
(async()=>{
 await ready();offer();await client.previewLinks();sendRelease=true;sendStatus=502;
 const pending=client.postLinks({confirmed:true});for(let i=0;i<4;i++)await tick();
 await client.postLinks({confirmed:true});assert.equal(sendCount,1);
 sendRelease();await pending;assert.equal(client.linkState.state,"unknown");
 await client.postLinks({confirmed:true});await client.previewLinks();
 assert.equal(sendCount,1);assert.equal(previewCount,1);
 assert.equal(client.phase,"listening");assert.ok(!agents[0].call.hungUp);
 await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_generation_reset_or_expired_preview_cannot_send():
    node(CHAT + r"""
(async()=>{
 await ready();offer();await client.previewLinks();
 now+=61000;await client.postLinks({confirmed:true});
 assert.equal(sendCount,0);assert.equal(client.linkState.state,"expired");
 now-=61000;offer("new-offer");await client.previewLinks();
 await client.pause();await client.postLinks({confirmed:true});
 assert.equal(sendCount,0);assert.equal(client.linkState.state,"unavailable");
 await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_thread_change_or_roster_loss_after_preview_blocks_send():
    node(CHAT + r"""
(async()=>{
 await ready();offer();await client.previewLinks();
 agents[0].call.info.threadId="19:different@thread.v2";
 await client.postLinks({confirmed:true});assert.equal(sendCount,0);
 agents[0].call.info.threadId=thread;offer("fresh");await client.previewLinks();
 agents[0].call.remoteParticipants[0].identifier={unknown:"unapproved"};
 await client.postLinks({confirmed:true});assert.equal(sendCount,0);
 for(let i=0;i<12;i++)await tick();assert.ok(agents[0].call.hungUp);
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_preview_validates_server_binding_and_never_renders_html():
    node(CHAT + r"""
(async()=>{
 await ready();offer();draft.thread_id="19:wrong@thread.v2";
 await client.previewLinks();assert.notEqual(client.linkState.state,"preview");
 await client.postLinks({confirmed:true});assert.equal(sendCount,0);
 assert.equal(client.phase,"listening");await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_preview_timeout_does_not_apply_late_response_or_stop_audio():
    node(CHAT + r"""
(async()=>{
 await ready();offer();previewRelease=true;
 const pending=client.previewLinks();for(let i=0;i<4;i++)await tick();
 const timer=callbacks.filter(c=>c.active&&c.ms===30000).at(-1);assert.ok(timer);
 timer.fn();await pending;assert.equal(client.linkState.state,"failed");
 previewRelease();for(let i=0;i<4;i++)await tick();
 assert.equal(client.linkState.state,"failed");assert.equal(sendCount,0);
 assert.equal(client.phase,"listening");await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_lost_send_response_blocks_retry_after_late_success_and_new_answer_clears_preview():
    node(CHAT + r"""
(async()=>{
 await ready();offer();await client.previewLinks();sendRelease=true;
 const pending=client.postLinks({confirmed:true});for(let i=0;i<4;i++)await tick();
 const timer=callbacks.filter(c=>c.active&&c.ms===30000).at(-1);timer.fn();
 await pending;assert.equal(client.linkState.state,"unknown");
 sendRelease();for(let i=0;i<4;i++)await tick();
 await client.postLinks({confirmed:true});assert.equal(sendCount,1);
 sockets[0].receive({type:"answer"});
 assert.equal(client.linkState.state,"unavailable");
 await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")


def test_response_body_stall_is_bounded_and_aborted_for_both_operations():
    node(CHAT + r"""
(async()=>{
 await ready();offer();previewBodyRelease=true;
 const preview=client.previewLinks();for(let i=0;i<6;i++)await tick();
 let timer=callbacks.filter(c=>c.ms===30000).at(-1);
 assert.ok(timer?.active,"preview body remains inside deadline");timer.fn();await preview;
 assert.equal(client.linkState.state,"failed");
 assert.equal(requests.at(-1).options.signal.aborted,true);
 previewBodyRelease();for(let i=0;i<4;i++)await tick();
 assert.equal(client.linkState.state,"failed");
 previewBodyRelease=null;offer("fresh");await client.previewLinks();sendBodyRelease=true;
 const send=client.postLinks({confirmed:true});for(let i=0;i<6;i++)await tick();
 timer=callbacks.filter(c=>c.ms===30000).at(-1);
 assert.ok(timer?.active,"send body remains inside deadline");timer.fn();await send;
 assert.equal(client.linkState.state,"unknown");
 assert.equal(requests.at(-1).options.signal.aborted,true);
 sendBodyRelease();for(let i=0;i<4;i++)await tick();
 await client.postLinks({confirmed:true});assert.equal(sendCount,1);
 assert.equal(client.linkState.state,"unknown");await client.stop();
})().catch(error=>{console.error(error);process.exitCode=1;});
""", STATIC / "teams-meeting.js")
