/* Evaluation-only base MQ Java probe. No credentials in argv or diagnostics.
 * Reflection permits compilation without redistributing IBM libraries; the api
 * preflight resolves IBM classes/constants on the actual client before mutation.
 */
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.security.cert.*;
import java.util.*;
import javax.net.ssl.*;

public final class BergenMQProbe {
    static final String MQ = "com.ibm.mq.";
    static Properties input = new Properties();
    static String value(String key) { return input.getProperty(key, ""); }
    static Object constant(String name) throws Exception {
        return Class.forName(MQ + "constants.MQConstants").getField(name).get(null);
    }
    static int number(String name) throws Exception { return ((Number)constant(name)).intValue(); }
    static Object make(String name) throws Exception { return Class.forName(MQ + name).getConstructor().newInstance(); }
    static void field(Object obj, String name, Object val) throws Exception { obj.getClass().getField(name).set(obj, val); }
    static Object field(Object obj, String name) throws Exception { return obj.getClass().getField(name).get(obj); }
    static Object call(Object obj, String name, Class<?>[] types, Object... args) throws Exception {
        try { return obj.getClass().getMethod(name, types).invoke(obj, args); }
        catch (InvocationTargetException e) {
            if (e.getCause() instanceof Exception) throw (Exception)e.getCause();
            throw e;
        }
    }
    static void call(Object obj, String name) throws Exception { call(obj, name, new Class<?>[0]); }
    static void check(boolean condition) { if (!condition) throw new AssertionError("ASSERTION"); }
    static void close(Object obj) throws Exception { if (obj != null) call(obj, "close"); }
    static void disconnect(Object obj) throws Exception { if (obj != null) call(obj, "disconnect"); }

    static Object connect(String side, String variant) throws Exception {
        Hashtable<String,Object> props = new Hashtable<>();
        props.put((String)constant("HOST_NAME_PROPERTY"), value(side + ".host"));
        props.put((String)constant("PORT_PROPERTY"), Integer.parseInt(value(side + ".port")));
        props.put((String)constant("CHANNEL_PROPERTY"), value(side + ".channel"));
        props.put((String)constant("TRANSPORT_PROPERTY"), constant("TRANSPORT_MQSERIES_CLIENT"));
        props.put((String)constant("USER_ID_PROPERTY"), value(side + ".username"));
        props.put((String)constant("PASSWORD_PROPERTY"), variant.equals("bad_password") ? UUID.randomUUID().toString() : value(side + ".password"));
        props.put((String)constant("USE_MQCSP_AUTHENTICATION_PROPERTY"), Boolean.TRUE);
        props.put((String)constant("SSL_CIPHER_SUITE_PROPERTY"), value(side + ".cipher"));
        props.put((String)constant("SSL_PEER_NAME_PROPERTY"), value(side + ".peer"));
        KeyStore trust = KeyStore.getInstance(KeyStore.getDefaultType());
        trust.load(null, null);
        try (InputStream in = Files.newInputStream(Paths.get(value(side + ".ca")))) {
            int i = 0;
            for (java.security.cert.Certificate cert : CertificateFactory.getInstance("X.509").generateCertificates(in))
                trust.setCertificateEntry("ca" + i++, cert);
            check(i > 0);
        }
        TrustManagerFactory factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        factory.init(trust);
        TrustManager[] managers = factory.getTrustManagers();
        if (variant.equals("bad_trust")) managers = new TrustManager[]{new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] chain, String auth) throws CertificateException { throw new CertificateException("audit rejection"); }
            public void checkServerTrusted(X509Certificate[] chain, String auth) throws CertificateException { throw new CertificateException("audit rejection"); }
        }};
        SSLContext ssl = SSLContext.getInstance("TLSv1.2");
        ssl.init(null, managers, new SecureRandom());
        props.put((String)constant("SSL_SOCKET_FACTORY_PROPERTY"), ssl.getSocketFactory());
        try {
            return Class.forName(MQ + "MQQueueManager").getConstructor(String.class, Hashtable.class)
                .newInstance(value(side + ".qmgr"), props);
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof Exception) throw (Exception)e.getCause();
            throw e;
        }
    }
    static Object queue(Object qm, String name, int options) throws Exception {
        return call(qm, "accessQueue", new Class<?>[]{String.class, int.class}, name, options | number("MQOO_FAIL_IF_QUIESCING"));
    }
    static Object message(byte[] body, int persistence, int priority, int expiry, byte[] correlation) throws Exception {
        Object msg = make("MQMessage");
        field(msg, "persistence", persistence); field(msg, "priority", priority); field(msg, "expiry", expiry);
        if (correlation != null) field(msg, "correlationId", correlation);
        call(msg, "write", new Class<?>[]{byte[].class}, (Object)body);
        return msg;
    }
    static byte[] put(Object qm, String name, byte[] body, boolean sync, int persistence, int priority, int expiry, byte[] correlation) throws Exception {
        Object q = queue(qm, name, number("MQOO_OUTPUT"));
        try {
            Object msg = message(body, persistence, priority, expiry, correlation), pmo = make("MQPutMessageOptions");
            field(pmo, "options", number(sync ? "MQPMO_SYNCPOINT" : "MQPMO_NO_SYNCPOINT") | number("MQPMO_FAIL_IF_QUIESCING"));
            call(q, "put", new Class<?>[]{Class.forName(MQ + "MQMessage"), Class.forName(MQ + "MQPutMessageOptions")}, msg, pmo);
            return (byte[])field(msg, "messageId");
        } finally { close(q); }
    }
    static Object get(Object qm, String name, byte[] id, byte[] correlation, boolean sync, boolean browse, int wait) throws Exception {
        Object q = queue(qm, name, number(browse ? "MQOO_BROWSE" : "MQOO_INPUT_SHARED"));
        try {
            Object msg = make("MQMessage"), gmo = make("MQGetMessageOptions");
            if (id != null) field(msg, "messageId", id);
            if (correlation != null) field(msg, "correlationId", correlation);
            field(gmo, "matchOptions", number(id != null ? "MQMO_MATCH_MSG_ID" : correlation != null ? "MQMO_MATCH_CORREL_ID" : "MQMO_NONE"));
            int options = number(sync ? "MQGMO_SYNCPOINT" : "MQGMO_NO_SYNCPOINT") | number("MQGMO_FAIL_IF_QUIESCING");
            if (browse) options |= number("MQGMO_BROWSE_FIRST");
            if (wait > 0) options |= number("MQGMO_WAIT");
            field(gmo, "options", options); field(gmo, "waitInterval", wait);
            call(q, "get", new Class<?>[]{Class.forName(MQ + "MQMessage"), Class.forName(MQ + "MQGetMessageOptions")}, msg, gmo);
            return msg;
        } finally { close(q); }
    }
    static byte[] body(Object msg) throws Exception {
        byte[] bytes = new byte[(Integer)call(msg, "getDataLength", new Class<?>[0])];
        call(msg, "readFully", new Class<?>[]{byte[].class}, (Object)bytes); return bytes;
    }
    static int reason(Throwable e) {
        for (Throwable t=e; t!=null; t=t.getCause()) {
            try { return t.getClass().getField("reasonCode").getInt(t); } catch (ReflectiveOperationException ignored) { }
        }
        return -1;
    }
    static boolean tlsFailure(Throwable e) {
        for (Throwable t=e; t!=null; t=t.getCause())
            if (t instanceof SSLException || t instanceof CertificateException) return true;
        return false;
    }
    static void empty(Object qm, String q, byte[] id) throws Exception {
        try { get(qm, q, id, null, false, false, 0); throw new AssertionError("unexpected message"); }
        catch (Exception e) { if (reason(e) != number("MQRC_NO_MSG_AVAILABLE")) throw e; }
    }
    static byte[] payload() {
        byte[] result = new byte[Integer.parseInt(value("size"))];
        new Random(Long.parseLong(value("seed"))).nextBytes(result); return result;
    }
    static void api() throws Exception {
        for (String cls : new String[]{"MQQueueManager", "MQMessage", "MQQueue", "MQPutMessageOptions", "MQGetMessageOptions"}) Class.forName(MQ + cls);
        for (String c : new String[]{"HOST_NAME_PROPERTY", "PORT_PROPERTY", "CHANNEL_PROPERTY", "USER_ID_PROPERTY", "PASSWORD_PROPERTY", "TRANSPORT_PROPERTY", "TRANSPORT_MQSERIES_CLIENT", "USE_MQCSP_AUTHENTICATION_PROPERTY", "SSL_CIPHER_SUITE_PROPERTY", "SSL_PEER_NAME_PROPERTY", "SSL_SOCKET_FACTORY_PROPERTY", "MQOO_OUTPUT", "MQOO_INPUT_SHARED", "MQOO_BROWSE", "MQOO_FAIL_IF_QUIESCING", "MQPMO_SYNCPOINT", "MQPMO_NO_SYNCPOINT", "MQPMO_FAIL_IF_QUIESCING", "MQGMO_SYNCPOINT", "MQGMO_NO_SYNCPOINT", "MQGMO_FAIL_IF_QUIESCING", "MQGMO_BROWSE_FIRST", "MQGMO_WAIT", "MQMO_MATCH_MSG_ID", "MQMO_MATCH_CORREL_ID", "MQMO_NONE", "MQRC_NO_MSG_AVAILABLE"}) constant(c);
    }
    static void run() throws Exception {
        String op=value("operation"), side=value("side"), q=value("queue"), other=value("other_queue");
        if (op.equals("api")) { api(); return; }
        if (op.equals("selftest")) { check(Arrays.equals(payload(), payload())); return; }
        Object qm=null, second=null;
        try {
            qm=connect(side, op);
            if (op.equals("connect") || op.equals("bad_password") || op.equals("bad_trust")) return;
            byte[] data=payload();
            int persistent=Integer.parseInt(value("persistence"));
            if (op.equals("empty") || op.equals("get_denied")) { get(qm,q,null,null,false,false,0); return; }
            if (op.equals("put_denied") || op.equals("oversize")) { put(qm,q,data,false,persistent,0,-1,null); return; }
            if (op.equals("roundtrip") || op.equals("alias") || op.startsWith("route") || op.equals("browse") || op.equals("correlation")) {
                byte[] correlation=op.equals("correlation") ? Arrays.copyOf(data,24) : null;
                boolean transaction=op.equals("route_commit") || op.equals("route_rollback");
                byte[] id=put(qm,q,data,transaction,persistent,0,-1,correlation);
                Object dest=qm;
                if (op.startsWith("route")) { second=connect(value("destination"), ""); dest=second; }
                String target=other.isEmpty() ? q : other;
                if (transaction) {
                    empty(dest,target,id);
                    call(qm,op.equals("route_commit") ? "commit" : "backout");
                    if (op.equals("route_rollback")) { empty(dest,target,id); return; }
                }
                Object got=get(dest,target,correlation==null?id:null,correlation,false,op.equals("browse"),10000);
                check(Arrays.equals(data,body(got)));
                check(Arrays.equals(id,(byte[])field(got,"messageId")));
                check((Integer)field(got,"persistence")==persistent);
                if (op.equals("browse")) check(Arrays.equals(data,body(get(dest,target,id,null,false,false,0))));
                empty(dest,target,id); return;
            }
            if (op.equals("put_commit") || op.equals("put_rollback") || op.equals("disconnect_rollback")) {
                second=connect(side, "");
                byte[] id=put(qm,q,data,true,persistent,0,-1,null);
                empty(second,q,id);
                if (op.equals("disconnect_rollback")) { disconnect(qm); qm=null; }
                else call(qm,op.equals("put_commit") ? "commit" : "backout");
                if (op.equals("put_commit")) check(Arrays.equals(data,body(get(second,q,id,null,false,false,10000))));
                else empty(second,q,id);
                return;
            }
            if (op.equals("get_commit") || op.equals("get_rollback")) {
                byte[] id=put(qm,q,data,false,persistent,0,-1,null);
                check(Arrays.equals(data,body(get(qm,q,id,null,true,false,0))));
                call(qm,op.equals("get_commit") ? "commit" : "backout");
                if (op.equals("get_commit")) empty(qm,q,id);
                else {
                    Object got=get(qm,q,id,null,false,false,0);
                    check(Arrays.equals(data,body(got))); check((Integer)field(got,"backoutCount") >= 1);
                }
                return;
            }
            if (op.equals("expiry")) {
                byte[] id=put(qm,q,data,false,persistent,0,10,null);
                Thread.sleep(1800); empty(qm,q,id); return;
            }
            if (op.equals("priority") || op.equals("fifo")) {
                byte[] low=put(qm,q,data,false,persistent,0,-1,null);
                byte[] high=put(qm,q,data,false,persistent,op.equals("priority")?9:0,-1,null);
                Object first=get(qm,q,null,null,false,false,0), last=get(qm,q,null,null,false,false,0);
                check(Arrays.equals((byte[])field(first,"messageId"),op.equals("priority")?high:low));
                check(Arrays.equals((byte[])field(last,"messageId"),op.equals("priority")?low:high)); return;
            }
            if (op.equals("full")) {
                byte[] id=put(qm,q,data,false,persistent,0,-1,null);
                try {
                    try { put(qm,q,data,false,persistent,0,-1,null); throw new AssertionError("full queue accepted message"); }
                    catch (Exception e) { if(reason(e)!=2053) throw e; }
                } finally { check(Arrays.equals(data,body(get(qm,q,id,null,false,false,0)))); }
                return;
            }
            throw new IllegalArgumentException("unsupported operation");
        } finally {
            try { disconnect(second); } finally { disconnect(qm); }
        }
    }
    public static void main(String[] args) {
        try {
            input.load(System.in);
            for (String key : input.stringPropertyNames()) input.setProperty(key,new String(Base64.getDecoder().decode(input.getProperty(key)),StandardCharsets.UTF_8));
            run(); System.out.println("{\"ok\":true,\"reason\":0,\"tls_failure\":false}");
        } catch (Throwable e) {
            System.out.println("{\"ok\":false,\"reason\":"+reason(e)+",\"tls_failure\":"+tlsFailure(e)+",\"category\":\""+(e instanceof AssertionError?"assertion":e instanceof ReflectiveOperationException?"api":"operation")+"\"}");
        }
    }
}
