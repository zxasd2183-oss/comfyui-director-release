package cn.borealos.glacier.geckopreview;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.net.URI;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Strict VLESS share-URL -> sing-box v1.14 JSON adapter for a small engine test.
 *
 * Accepts only TLS/REALITY with tcp or ws, no allowInsecure, no unexpected
 * flow, no insecure transport and no implicit DIRECT outbound.
 * Do not log or serialize the original link outside the temporary config.
 */
public final class VlessLink {
    final String host;
    final int port;
    final String uuid;
    final String security;
    final String sni;
    final String publicKey;
    final String shortId;
    final String flow;
    final String transport;
    final String path;
    final String wsHost;
    final String fingerprint;
    final String alpn;

    private VlessLink(String host, int port, String uuid, String security,
                      String sni, String publicKey, String shortId, String flow,
                      String transport, String path, String wsHost,
                      String fingerprint, String alpn) {
        this.host=host; this.port=port; this.uuid=uuid; this.security=security;
        this.sni=sni; this.publicKey=publicKey; this.shortId=shortId;
        this.flow=flow; this.transport=transport; this.path=path;
        this.wsHost=wsHost; this.fingerprint=fingerprint; this.alpn=alpn;
    }

    private static Map<String,String> params(String q) throws Exception {
        Map<String,String> p=new HashMap<>();
        if(q==null||q.isEmpty()) return p;
        if(q.length()>2048) throw new Exception("节点参数太长");
        for(String pair:q.split("&")) {
            if(pair.isEmpty()) continue;
            String[] parts=pair.split("=",2);
            String key=URLDecoder.decode(parts[0],"UTF-8");
            String val=parts.length==2?URLDecoder.decode(parts[1],"UTF-8"):"";
            if(key.length()>64||val.length()>1024||p.containsKey(key))
                throw new Exception("VLESS 参数重复或过长");
            p.put(key,val);
        }
        return p;
    }

    private static String get(Map<String,String> p,String name,String fallback) {
        String val=p.get(name);
        return val==null?fallback:val.trim();
    }

    public static VlessLink parse(String value) throws Exception {
        if(value==null||value.length()<16||value.length()>4096)
            throw new Exception("请输入完整的 vless:// 节点链接");
        URI u;
        try { u=new URI(value.trim()); }
        catch(Exception e) { throw new Exception("VLESS 链接格式无效"); }
        if(!"vless".equalsIgnoreCase(u.getScheme())||u.getHost()==null)
            throw new Exception("仅支持标准 vless:// 分享链接");
        if(u.getPort()<=0||u.getPort()>65535)
            throw new Exception("节点端口无效");
        String id=u.getRawUserInfo();
        if(id==null||id.contains(":")) throw new Exception("VLESS 用户 UUID 格式无效");
        try { UUID.fromString(id); }
        catch(Exception e) { throw new Exception("VLESS UUID 无效"); }
        Map<String,String> p=params(u.getRawQuery());
        if(!"none".equalsIgnoreCase(get(p,"encryption","none")))
            throw new Exception("不支持此 VLESS 加密类型");
        for(String name:new String[]{"allowInsecure","insecure"}) {
            if("1".equals(get(p,name,"0"))||
                    "true".equalsIgnoreCase(get(p,name,"false")))
                throw new Exception("拒绝不安全的 TLS 设置");
        }
        String security=get(p,"security","");
        if(!"tls".equals(security)&&!"reality".equals(security))
            throw new Exception("实验版仅支持 TLS 或 REALITY 节点");
        String type=get(p,"type","tcp");
        if(!"tcp".equals(type)&&!"ws".equals(type))
            throw new Exception("实验版暂支持 TCP 和 WebSocket 传输");
        String flow=get(p,"flow","");
        if(!flow.isEmpty()&&!"xtls-rprx-vision".equals(flow))
            throw new Exception("暂不支持这个 VLESS flow");
        if("ws".equals(type)&&!flow.isEmpty())
            throw new Exception("WebSocket 不支持 Vision flow");
        String pbk=get(p,"pbk","");
        String sid=get(p,"sid","");
        if("reality".equals(security)&&(pbk.isEmpty()||pbk.length()>128))
            throw new Exception("REALITY 必须提供 pbk 公钥");
        String sni=get(p,"sni",u.getHost());
        if(sni.isEmpty()||sni.length()>255) throw new Exception("无效的 TLS SNI");
        String fp=get(p,"fp","chrome");
        if(fp.length()>30) throw new Exception("浏览器指纹无效");
        return new VlessLink(u.getHost(),u.getPort(),id,security,sni,pbk,sid,
                flow,type,get(p,"path","/"),get(p,"host",""),fp,
                get(p,"alpn",""));
    }

    /** No direct outbound/fallback in the generated node routing graph. */
    public JSONObject singBoxConfig(int listenPort) throws JSONException {
        JSONObject inbound=new JSONObject()
                .put("type","socks")
                .put("tag","browser-local")
                .put("listen","127.0.0.1")
                .put("listen_port",listenPort);
        JSONObject tls=new JSONObject()
                .put("enabled",true)
                .put("server_name",sni)
                .put("insecure",false)
                .put("utls",new JSONObject()
                        .put("enabled",true).put("fingerprint",fingerprint));
        if(!alpn.isEmpty()) {
            JSONArray values=new JSONArray();
            for(String item:alpn.split(",")) if(!item.trim().isEmpty()) values.put(item.trim());
            if(values.length()>0) tls.put("alpn",values);
        }
        if("reality".equals(security))
            tls.put("reality",new JSONObject()
                    .put("enabled",true)
                    .put("public_key",publicKey)
                    .put("short_id",shortId));
        JSONObject outbound=new JSONObject()
                .put("type","vless")
                .put("tag","vless-node")
                .put("server",host)
                .put("server_port",port)
                .put("uuid",uuid)
                .put("tls",tls);
        if(!flow.isEmpty()) outbound.put("flow",flow);
        if("ws".equals(transport)) {
            JSONObject ws=new JSONObject().put("type","ws").put("path",path);
            if(!wsHost.isEmpty())
                ws.put("headers",new JSONObject().put("Host",wsHost));
            outbound.put("transport",ws);
        }
        return new JSONObject()
                .put("log",new JSONObject().put("level","warn"))
                .put("inbounds",new JSONArray().put(inbound))
                .put("outbounds",new JSONArray().put(outbound))
                .put("route",new JSONObject().put("final","vless-node"));
    }

    @Override public String toString() {
        // Never include credentials or server details in exception/log output.
        return "VLESS node (redacted)";
    }
}
