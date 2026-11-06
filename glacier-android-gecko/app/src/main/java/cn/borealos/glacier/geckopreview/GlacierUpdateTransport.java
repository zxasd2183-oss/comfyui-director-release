package cn.borealos.glacier.geckopreview;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * M05 update-only HTTPS transport. Never uses a default JVM URLConnection
 * while VLESS is selected: connects to 127.0.0.1 SOCKS5 and sends the
 * destination hostname with ATYP=domain, so DNS and HTTPS traffic remain
 * inside the selected proxy. No direct-network retry is ever attempted.
 *
 * Restricts each redirect to fixed HTTPS GitHub source/asset hosts.
 * This separate transport NEVER supplies arbitrary cookies or browser data.
 */
final class GlacierUpdateTransport {
    static final String API = "https://api.github.com/repos/zxasd2183-oss/comfyui-director-release/releases?per_page=40";
    private static final int CONNECT_TIMEOUT = 15000;
    private static final int READ_TIMEOUT = 30000;
    private static final int MAX_REDIRECTS = 5;
    private static final int MAX_HEADER = 24 * 1024;

    private GlacierUpdateTransport() {}

    static boolean allowed(String address) {
        try {
            URI uri = new URI(address);
            if (!"https".equalsIgnoreCase(uri.getScheme()) ||
                    uri.getRawUserInfo()!=null || uri.getFragment()!=null ||
                    (uri.getPort()!=-1 && uri.getPort()!=443)) return false;
            String host=uri.getHost();
            if(host==null)return false;
            host=host.toLowerCase(Locale.ROOT);
            return host.equals("api.github.com") || host.equals("github.com")
                    || host.equals("release-assets.githubusercontent.com")
                    || host.equals("objects.githubusercontent.com");
        } catch(Exception e) {
            return false;
        }
    }

    private static void readFully(InputStream in,byte[] b) throws IOException {
        int off=0;
        while(off<b.length) {
            int n=in.read(b,off,b.length-off);
            if(n==-1)throw new IOException("Short SOCKS5 response");
            off+=n;
        }
    }

    private static int readByte(InputStream in) throws IOException {
        int b=in.read();
        if(b<0)throw new IOException("Unexpected EOF");
        return b;
    }

    static Socket connectSocks(String host, int port, int socksPort) throws IOException {
        byte[] domain=host.getBytes(StandardCharsets.US_ASCII);
        if(domain.length==0||domain.length>255)
            throw new IOException("Invalid SOCKS hostname");
        Socket s=new Socket();
        boolean ok=false;
        try {
            // The only unproxied socket connects to localhost, NEVER a remote host.
            s.connect(new InetSocketAddress("127.0.0.1",socksPort),CONNECT_TIMEOUT);
            s.setSoTimeout(READ_TIMEOUT);
            InputStream input=s.getInputStream();
            OutputStream out=s.getOutputStream();
            out.write(new byte[]{5,1,0});
            out.flush();
            if(readByte(input)!=5 || readByte(input)!=0)
                throw new IOException("SOCKS5 authentication rejected");
            ByteArrayOutputStream request=new ByteArrayOutputStream();
            request.write(5);request.write(1);request.write(0);request.write(3);
            request.write(domain.length);request.write(domain,0,domain.length);
            request.write((port>>8)&255);request.write(port&255);
            out.write(request.toByteArray());out.flush();
            if(readByte(input)!=5||readByte(input)!=0||readByte(input)!=0)
                throw new IOException("SOCKS5 proxy refused update connection");
            int type=readByte(input),extra;
            if(type==1)extra=4;
            else if(type==4)extra=16;
            else if(type==3)extra=readByte(input);
            else throw new IOException("Unexpected SOCKS5 address type");
            if(extra<1||extra>255)throw new IOException("Invalid SOCKS5 address");
            readFully(input,new byte[extra+2]);
            ok=true;
            return s;
        } finally {
            if(!ok)try{s.close();}catch(Exception ignored){}
        }
    }

    private static String readLine(InputStream in,int limit) throws IOException {
        ByteArrayOutputStream b=new ByteArrayOutputStream();
        while(b.size()<=limit) {
            int ch=in.read();
            if(ch==-1)throw new IOException("Premature HTTP header end");
            if(ch=='\n') {
                byte[] data=b.toByteArray();
                int len=data.length;
                if(len>0&&data[len-1]=='\r')len--;
                return new String(data,0,len,StandardCharsets.US_ASCII);
            }
            b.write(ch);
        }
        throw new IOException("HTTPS header too large");
    }

    private static final class Chunked extends InputStream {
        final InputStream inner;
        long remaining=0;
        boolean end=false;
        Chunked(InputStream in){inner=in;}
        private void next() throws IOException {
            String line=readLine(inner,128);
            int semi=line.indexOf(';');
            if(semi>=0)line=line.substring(0,semi);
            try{remaining=Long.parseLong(line.trim(),16);}
            catch(NumberFormatException ex){throw new IOException("Bad HTTP chunk");}
            if(remaining<0||remaining>1_000_000_000L)
                throw new IOException("Invalid chunk length");
            if(remaining==0) {
                int total=0;
                while(true) {
                    String trailer=readLine(inner,256);
                    total+=trailer.length();
                    if(total>4096)throw new IOException("Too many trailers");
                    if(trailer.isEmpty())break;
                }
                end=true;
            }
        }
        @Override public int read() throws IOException {
            byte[] b=new byte[1];
            return read(b,0,1)==-1?-1:(b[0]&255);
        }
        @Override public int read(byte[] b,int off,int len) throws IOException {
            if(len==0)return 0;
            if(end)return -1;
            if(remaining==0)next();
            if(end)return -1;
            int read=inner.read(b,off,(int)Math.min(len,remaining));
            if(read<0)throw new IOException("Truncated HTTP chunk");
            remaining-=read;
            if(remaining==0) {
                if(readByte(inner)!='\r'||readByte(inner)!='\n')
                    throw new IOException("Bad HTTP chunk terminator");
            }
            return read;
        }
    }

    static final class Response implements AutoCloseable {
        final InputStream body;
        final String contentLength;
        final String url;
        private final Socket socket;
        Response(InputStream data,String length,String address,Socket socket) {
            this.body=data;this.contentLength=length;this.url=address;this.socket=socket;
        }
        @Override public void close() throws IOException {socket.close();}
    }

    static Response open(String address,boolean proxied,int socksPort) throws IOException {
        for(int redirects=0;redirects<=MAX_REDIRECTS;redirects++) {
            if(!allowed(address))throw new IOException("Untrusted update destination");
            URI uri;
            try{uri=new URI(address);}catch(Exception ex){throw new IOException("Malformed HTTPS URI",ex);}
            String host=uri.getHost();
            String path=uri.getRawPath();
            if(path==null||path.isEmpty())path="/";
            if(uri.getRawQuery()!=null)path+="?"+uri.getRawQuery();
            Socket base=proxied ? connectSocks(host,443,socksPort) : new Socket();
            SSLSocket ssl=null;
            boolean transferred=false;
            try {
                if(!proxied) {
                    base.connect(new InetSocketAddress(host,443),CONNECT_TIMEOUT);
                    base.setSoTimeout(READ_TIMEOUT);
                }
                ssl=(SSLSocket)((SSLSocketFactory)SSLSocketFactory.getDefault())
                        .createSocket(base,host,443,true);
                SSLParameters params=ssl.getSSLParameters();
                params.setEndpointIdentificationAlgorithm("HTTPS");
                ssl.setSSLParameters(params);
                ssl.setSoTimeout(READ_TIMEOUT);
                ssl.startHandshake();
                String req="GET "+path+" HTTP/1.1\r\nHost: "+host+
                        "\r\nUser-Agent: Glacier-Android-Updater/1.0"+
                        "\r\nAccept: application/vnd.github+json, application/octet-stream"+
                        "\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n";
                ssl.getOutputStream().write(req.getBytes(StandardCharsets.US_ASCII));
                ssl.getOutputStream().flush();
                InputStream input=new BufferedInputStream(ssl.getInputStream(),32768);
                String status=readLine(input,512);
                String[] statusParts=status.split(" ",3);
                if(statusParts.length<2||!statusParts[0].startsWith("HTTP/1."))
                    throw new IOException("Unrecognized HTTPS status");
                int code;
                try{code=Integer.parseInt(statusParts[1]);}
                catch(Exception ex){throw new IOException("Invalid HTTP status",ex);}
                Map<String,String> headers=new HashMap<>();
                int headerTotal=status.length();
                while(true) {
                    String line=readLine(input,8192);
                    headerTotal+=line.length();
                    if(headerTotal>MAX_HEADER)throw new IOException("Too many headers");
                    if(line.isEmpty())break;
                    int colon=line.indexOf(':');
                    if(colon>0)headers.put(line.substring(0,colon).trim()
                            .toLowerCase(Locale.ROOT),line.substring(colon+1).trim());
                }
                if(code==301||code==302||code==303||code==307||code==308) {
                    String target=headers.get("location");
                    if(target==null)throw new IOException("Missing HTTPS redirect target");
                    URI redirected=uri.resolve(target);
                    address=redirected.toString();
                    if(!allowed(address))throw new IOException("Redirect left HTTPS allowlist");
                    ssl.close();ssl=null;
                    continue;
                }
                if(code!=200)throw new IOException("Update source returned HTTP "+code);
                String transfer=headers.getOrDefault("transfer-encoding","");
                if(!transfer.isEmpty()&&!transfer.equalsIgnoreCase("chunked"))
                    throw new IOException("Unexpected HTTP transfer encoding");
                InputStream body="chunked".equalsIgnoreCase(transfer)?
                        new Chunked(input):input;
                Response result=new Response(body,headers.get("content-length"),address,ssl);
                transferred=true;
                ssl=null;
                return result;
            } finally {
                // Failed handshakes, redirects and HTTP errors close both
                // the TLS wrapper and its underlying SOCKS/direct socket.
                if(!transferred) {
                    if(ssl!=null)try{ssl.close();}catch(IOException ignored){}
                    if(!base.isClosed())try{base.close();}catch(IOException ignored){}
                }
            }
        }
        throw new IOException("Too many HTTPS redirects");
    }

    static byte[] fetchSmall(String url,boolean proxy,int socksPort,int cap)
            throws IOException {
        try(Response response=open(url,proxy,socksPort)) {
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buffer=new byte[8192];
            int n;
            while((n=response.body.read(buffer))!=-1) {
                if(out.size()+n>cap)throw new IOException("Update index exceeds size cap");
                out.write(buffer,0,n);
            }
            return out.toByteArray();
        }
    }
}
