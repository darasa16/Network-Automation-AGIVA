--
-- PostgreSQL database dump
--

\restrict ekVmEIzLdKMVYf4ahkGMEYRNCGnb0T58dQ1qyeOxMAYpDVseV6FdY5jkG132kDC

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alerts (
    alert_id integer NOT NULL,
    device_id integer NOT NULL,
    type character varying(50) NOT NULL,
    severity character varying(20),
    message text NOT NULL,
    triggered_at timestamp without time zone NOT NULL,
    acknowledged boolean,
    acknowledged_by character varying(100),
    resolved_at timestamp without time zone
);


ALTER TABLE public.alerts OWNER TO postgres;

--
-- Name: alerts_alert_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.alerts_alert_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alerts_alert_id_seq OWNER TO postgres;

--
-- Name: alerts_alert_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.alerts_alert_id_seq OWNED BY public.alerts.alert_id;


--
-- Name: backup_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.backup_history (
    backup_id integer NOT NULL,
    device_id integer NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    file_path text NOT NULL,
    file_size character varying(50),
    status character varying(20) NOT NULL
);


ALTER TABLE public.backup_history OWNER TO postgres;

--
-- Name: backup_history_backup_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.backup_history_backup_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.backup_history_backup_id_seq OWNER TO postgres;

--
-- Name: backup_history_backup_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.backup_history_backup_id_seq OWNED BY public.backup_history.backup_id;


--
-- Name: device_status_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_status_logs (
    log_id bigint NOT NULL,
    device_id integer NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    status character varying(20) NOT NULL,
    cpu_usage double precision,
    mem_usage double precision,
    traffic_mbps double precision
);


ALTER TABLE public.device_status_logs OWNER TO postgres;

--
-- Name: device_status_logs_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_status_logs_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_status_logs_log_id_seq OWNER TO postgres;

--
-- Name: device_status_logs_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_status_logs_log_id_seq OWNED BY public.device_status_logs.log_id;


--
-- Name: devices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.devices (
    device_id integer NOT NULL,
    name character varying(100) NOT NULL,
    ip_address character varying(45) NOT NULL,
    vendor character varying(50) NOT NULL,
    site character varying(100) NOT NULL,
    status character varying(20),
    cpu_usage double precision,
    mem_usage double precision,
    traffic_mbps double precision,
    uptime character varying(100),
    credential_ref character varying(100),
    last_polled timestamp without time zone
);


ALTER TABLE public.devices OWNER TO postgres;

--
-- Name: devices_device_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.devices_device_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.devices_device_id_seq OWNER TO postgres;

--
-- Name: devices_device_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.devices_device_id_seq OWNED BY public.devices.device_id;


--
-- Name: telegram_message_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.telegram_message_logs (
    id integer NOT NULL,
    alert_id integer,
    chat_id character varying(50) NOT NULL,
    message_type character varying(50) NOT NULL,
    content text NOT NULL,
    status character varying(20),
    sent_at timestamp without time zone
);


ALTER TABLE public.telegram_message_logs OWNER TO postgres;

--
-- Name: telegram_message_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.telegram_message_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.telegram_message_logs_id_seq OWNER TO postgres;

--
-- Name: telegram_message_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.telegram_message_logs_id_seq OWNED BY public.telegram_message_logs.id;


--
-- Name: telegram_whitelist; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.telegram_whitelist (
    id integer NOT NULL,
    chat_id character varying(50) NOT NULL,
    telegram_username character varying(100) NOT NULL,
    engineer_name character varying(150) NOT NULL,
    role character varying(80),
    is_active boolean,
    registered_at timestamp without time zone
);


ALTER TABLE public.telegram_whitelist OWNER TO postgres;

--
-- Name: telegram_whitelist_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.telegram_whitelist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.telegram_whitelist_id_seq OWNER TO postgres;

--
-- Name: telegram_whitelist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.telegram_whitelist_id_seq OWNED BY public.telegram_whitelist.id;


--
-- Name: alerts alert_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts ALTER COLUMN alert_id SET DEFAULT nextval('public.alerts_alert_id_seq'::regclass);


--
-- Name: backup_history backup_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.backup_history ALTER COLUMN backup_id SET DEFAULT nextval('public.backup_history_backup_id_seq'::regclass);


--
-- Name: device_status_logs log_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_status_logs ALTER COLUMN log_id SET DEFAULT nextval('public.device_status_logs_log_id_seq'::regclass);


--
-- Name: devices device_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices ALTER COLUMN device_id SET DEFAULT nextval('public.devices_device_id_seq'::regclass);


--
-- Name: telegram_message_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_message_logs ALTER COLUMN id SET DEFAULT nextval('public.telegram_message_logs_id_seq'::regclass);


--
-- Name: telegram_whitelist id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_whitelist ALTER COLUMN id SET DEFAULT nextval('public.telegram_whitelist_id_seq'::regclass);


--
-- Data for Name: alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alerts (alert_id, device_id, type, severity, message, triggered_at, acknowledged, acknowledged_by, resolved_at) FROM stdin;
1	3	CPU_THRESHOLD_EXCEEDED	WARNING	High CPU utilization detected (> 85%) on Core CPU 0.	2026-09-30 04:17:09.903054	t	Web NOC Admin	\N
2	5	HOST_UNREACHABLE	CRITICAL	Device unreachable after 2 consecutive polling attempts (ICMP/SSH Timeout).	2026-09-30 04:04:09.903054	t	Web NOC Admin	\N
3	7	INTERFACE_DOWN	CRITICAL	Interface GigabitEthernet0/1 changed state to administratively down.	2026-09-30 03:34:09.903054	t	@agiva_noc_lead via Telegram	\N
4	6	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.	2026-09-30 05:34:00.413563	f	\N	\N
5	4	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Branch-Sby mencapai 88.5%.	2026-09-30 05:34:01.645997	f	\N	\N
6	6	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.	2026-09-30 05:34:02.097337	f	\N	\N
7	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-09-30 05:34:02.307137	f	\N	\N
8	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-09-30 05:34:02.528798	t	Web NOC Admin	\N
9	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-09-30 07:44:24.273345	f	\N	\N
10	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-01 14:17:53	f	\N	\N
11	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-01 14:20:04	f	\N	\N
12	8	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.	2026-10-01 14:21:32	f	\N	\N
13	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-10-01 14:53:21	f	\N	\N
14	2	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Switch-Dist-01 mencapai 88.5%.	2026-10-01 15:21:22	f	\N	\N
15	8	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.	2026-10-01 15:21:34	f	\N	\N
16	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-10-01 16:37:43	f	\N	\N
17	6	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.	2026-10-02 12:44:30	f	\N	\N
18	4	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Branch-Sby mencapai 88.5%.	2026-10-02 12:51:03	f	\N	\N
19	8	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.	2026-10-02 13:27:16	f	\N	\N
20	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-02 15:09:42	f	\N	\N
21	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-10-02 15:46:08	f	\N	\N
22	1	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.	2026-10-02 16:04:27	f	\N	\N
23	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-02 16:11:31	f	\N	\N
24	2	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Switch-Dist-01 mencapai 88.5%.	2026-10-02 16:11:47	f	\N	\N
25	6	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.	2026-10-02 16:12:46	f	\N	\N
26	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-02 16:23:46.842032	f	\N	\N
27	3	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.	2026-10-02 16:25:22.399412	f	\N	\N
28	4	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Branch-Sby mencapai 88.5%.	2026-10-02 16:25:33.393315	f	\N	\N
29	8	CPU_OVERLOAD	WARNING	Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.	2026-10-02 16:53:17.458146	f	\N	\N
\.


--
-- Data for Name: backup_history; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.backup_history (backup_id, device_id, "timestamp", file_path, file_size, status) FROM stdin;
1	1	2026-09-29 20:29:09.903054	/backups/HQ/Router-Core-01/2026-09-28_config.txt	45.2 KB	SUCCESS
2	2	2026-09-29 20:29:09.903054	/backups/HQ/Switch-Dist-01/2026-09-28_config.txt	128.6 KB	SUCCESS
3	3	2026-09-29 20:29:09.903054	/backups/Gateway/Router-Edge-01/2026-09-28_config.txt	56.8 KB	SUCCESS
4	5	2026-09-29 20:29:09.903054	-	0 KB	FAILED
\.


--
-- Data for Name: device_status_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_status_logs (log_id, device_id, "timestamp", status, cpu_usage, mem_usage, traffic_mbps) FROM stdin;
1	1	2026-09-29 16:29:09.903054	UP	27.9	48.5	122.6
2	1	2026-09-29 17:29:09.903054	UP	42	51.1	158.8
3	1	2026-09-29 18:29:09.903054	UP	22.3	46.7	120.5
4	1	2026-09-29 19:29:09.903054	UP	28.1	42.9	144.9
5	1	2026-09-29 20:29:09.903054	UP	48.4	49.8	139.3
6	1	2026-09-29 21:29:09.903054	UP	26.4	51.6	123.2
7	1	2026-09-29 22:29:09.903054	UP	41.1	45.9	116.1
8	1	2026-09-29 23:29:09.903054	UP	23	51.2	165.9
9	1	2026-09-30 00:29:09.903054	UP	45.1	47.5	151
10	1	2026-09-30 01:29:09.903054	UP	44.2	48.8	131.4
11	1	2026-09-30 02:29:09.903054	UP	46	52.3	151.1
12	1	2026-09-30 03:29:09.903054	UP	29.3	43.1	125.2
13	2	2026-09-29 16:29:09.903054	UP	27	41	60.4
14	2	2026-09-29 17:29:09.903054	UP	31.5	38.7	110.8
15	2	2026-09-29 18:29:09.903054	UP	16.4	39.2	73.1
16	2	2026-09-29 19:29:09.903054	UP	15.4	44.7	110.4
17	2	2026-09-29 20:29:09.903054	UP	15.3	42.6	77.1
18	2	2026-09-29 21:29:09.903054	UP	15.5	40.3	92.5
19	2	2026-09-29 22:29:09.903054	UP	28.2	43.2	70.9
20	2	2026-09-29 23:29:09.903054	UP	35.2	39.8	82.9
21	2	2026-09-30 00:29:09.903054	UP	23.7	41.5	75.5
22	2	2026-09-30 01:29:09.903054	UP	19.5	42.1	108.8
23	2	2026-09-30 02:29:09.903054	UP	25.5	42.3	72.7
24	2	2026-09-30 03:29:09.903054	UP	21.7	44.2	84.6
25	3	2026-09-29 16:29:09.903054	UP	71.1	65.5	195.3
26	3	2026-09-29 17:29:09.903054	UP	44.3	58.6	196.8
27	3	2026-09-29 18:29:09.903054	UP	43.9	63.7	230.7
28	3	2026-09-29 19:29:09.903054	UP	61.4	59.8	212.3
29	3	2026-09-29 20:29:09.903054	UP	68.4	69.1	222.7
30	3	2026-09-29 21:29:09.903054	UP	65.7	59.4	189.4
31	3	2026-09-29 22:29:09.903054	UP	53.5	66.6	204.2
32	3	2026-09-29 23:29:09.903054	UP	65.3	62.1	190.8
33	3	2026-09-30 00:29:09.903054	UP	73	65.1	227
34	3	2026-09-30 01:29:09.903054	UP	65.5	62.9	217.9
35	3	2026-09-30 02:29:09.903054	UP	57.4	62.7	197.4
36	3	2026-09-30 03:29:09.903054	UP	49.1	65.7	234.1
37	4	2026-09-29 16:29:09.903054	UP	5	36.5	64.7
38	4	2026-09-29 17:29:09.903054	UP	8.4	36.3	30.8
39	4	2026-09-29 18:29:09.903054	UP	27.5	30.5	53.6
40	4	2026-09-29 19:29:09.903054	UP	11.2	29.5	28.1
41	4	2026-09-29 20:29:09.903054	UP	5.6	30	29.5
42	4	2026-09-29 21:29:09.903054	UP	20.8	35.6	26.7
43	4	2026-09-29 22:29:09.903054	UP	19.9	29.3	48.9
44	4	2026-09-29 23:29:09.903054	UP	9.8	28.4	69.4
45	4	2026-09-30 00:29:09.903054	UP	16	33.1	60.1
46	4	2026-09-30 01:29:09.903054	UP	24.1	29.5	22.5
47	4	2026-09-30 02:29:09.903054	UP	32.1	25.8	48.9
48	4	2026-09-30 03:29:09.903054	UP	18.9	31.2	74.8
49	6	2026-09-29 16:29:09.903054	UP	5	33.8	27.4
50	6	2026-09-29 17:29:09.903054	UP	10.3	33.1	10
51	6	2026-09-29 18:29:09.903054	UP	9.5	25.4	10
52	6	2026-09-29 19:29:09.903054	UP	8.1	24.5	33.4
53	6	2026-09-29 20:29:09.903054	UP	12.5	34.5	10
54	6	2026-09-29 21:29:09.903054	UP	24.8	32.1	10
55	6	2026-09-29 22:29:09.903054	UP	5	28.7	10
56	6	2026-09-29 23:29:09.903054	UP	5	22.9	41.9
57	6	2026-09-30 00:29:09.903054	UP	14.4	23.6	29.9
58	6	2026-09-30 01:29:09.903054	UP	5	32.4	10
59	6	2026-09-30 02:29:09.903054	UP	24.2	27.4	16.4
60	6	2026-09-30 03:29:09.903054	UP	5	33.5	22.6
61	8	2026-09-29 16:29:09.903054	UP	45.7	58.1	51.7
62	8	2026-09-29 17:29:09.903054	UP	38.3	57.1	91.8
63	8	2026-09-29 18:29:09.903054	UP	45.8	53	66.2
64	8	2026-09-29 19:29:09.903054	UP	32.1	55.5	71.7
65	8	2026-09-29 20:29:09.903054	UP	55.5	56.9	46.8
66	8	2026-09-29 21:29:09.903054	UP	50.1	49.8	41.9
67	8	2026-09-29 22:29:09.903054	UP	41.4	55.2	46.3
68	8	2026-09-29 23:29:09.903054	UP	40.4	48.7	63.2
69	8	2026-09-30 00:29:09.903054	UP	28.5	55.8	76.4
70	8	2026-09-30 01:29:09.903054	UP	54.5	51.3	54.5
71	8	2026-09-30 02:29:09.903054	UP	45.6	53.6	73.5
72	8	2026-09-30 03:29:09.903054	UP	31.7	53.5	65.4
\.


--
-- Data for Name: devices; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.devices (device_id, name, ip_address, vendor, site, status, cpu_usage, mem_usage, traffic_mbps, uptime, credential_ref, last_polled) FROM stdin;
5	Switch-Access-Bdg	10.20.30.2	Cisco	Bandung Site	DOWN	0	0	0	Offline	env_vault	2026-09-30 04:29:09.90054
7	Firewall-Ext-01	192.168.100.1	Cisco	DMZ Gateway	DOWN	0	0	0	Offline	env_vault	2026-09-30 04:29:09.900543
1	Router-Core-01	192.168.1.1	MikroTik	Data Center HQ	UP	31.2	52.3	203.7	42 days, 14 hours	env_vault	2026-10-06 16:18:27.636576
2	Switch-Dist-01	192.168.1.2	Cisco	Data Center HQ	UP	46.4	35.1	74.1	89 days, 06 hours	env_vault	2026-10-06 16:18:27.636576
3	Router-Edge-01	192.168.1.3	MikroTik	Gateway IDC	UP	45.6	66.7	189.4	15 days, 02 hours	env_vault	2026-10-06 16:18:27.636576
4	Router-Branch-Sby	10.10.20.1	MikroTik	Surabaya Branch	UP	67	31.2	39.2	4 days, 11 hours	env_vault	2026-10-06 16:18:27.636576
6	Router-Backup-01	192.168.1.254	Cisco	Data Center HQ	UP	46.4	43.4	43.8	120 days, 18 hours	env_vault	2026-10-06 16:18:27.636576
8	Router-Distribution-02	10.10.10.1	MikroTik	Medan Branch	UP	29	55.3	48.9	28 days, 09 hours	env_vault	2026-10-06 16:18:27.636576
\.


--
-- Data for Name: telegram_message_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.telegram_message_logs (id, alert_id, chat_id, message_type, content, status, sent_at) FROM stdin;
15	11	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #11\n• *Perangkat:* `Router-Edge-01` (192.168.1.3)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.\n• *Waktu:* 2026-10-01 14:20:04 WIB\n\n👉 Ketik `/ack 11` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 14:20:05
16	12	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #12\n• *Perangkat:* `Router-Distribution-02` (10.10.10.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.\n• *Waktu:* 2026-10-01 14:21:32 WIB\n\n👉 Ketik `/ack 12` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 14:21:33
17	13	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #13\n• *Perangkat:* `Router-Core-01` (192.168.1.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.\n• *Waktu:* 2026-10-01 14:53:21 WIB\n\n👉 Ketik `/ack 13` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 14:53:22
18	14	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #14\n• *Perangkat:* `Switch-Dist-01` (192.168.1.2)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Switch-Dist-01 mencapai 88.5%.\n• *Waktu:* 2026-10-01 15:21:22 WIB\n\n👉 Ketik `/ack 14` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 15:21:23
19	15	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #15\n• *Perangkat:* `Router-Distribution-02` (10.10.10.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.\n• *Waktu:* 2026-10-01 15:21:34 WIB\n\n👉 Ketik `/ack 15` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 15:21:35
20	16	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #16\n• *Perangkat:* `Router-Core-01` (192.168.1.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.\n• *Waktu:* 2026-10-01 16:37:43 WIB\n\n👉 Ketik `/ack 16` di bot untuk konfirmasi penanganan.	SENT	2026-10-01 16:37:44
21	17	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #17\n• *Perangkat:* `Router-Backup-01` (192.168.1.254)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 12:44:30 WIB\n\n👉 Ketik `/ack 17` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 12:44:31
22	1	-1004429503436	COMMAND_REPLY	✅ *[NOC AGIVA - ALERT ACKNOWLEDGED]*\n\nAlert #1 (CPU_THRESHOLD_EXCEEDED) pada `Router-Edge-01` telah di-acknowledge oleh Web NOC Admin.	SENT	2026-10-02 12:44:32
23	18	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #18\n• *Perangkat:* `Router-Branch-Sby` (10.10.20.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Branch-Sby mencapai 88.5%.\n• *Waktu:* 2026-10-02 12:51:03 WIB\n\n👉 Ketik `/ack 18` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 12:51:04
24	19	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #19\n• *Perangkat:* `Router-Distribution-02` (10.10.10.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.\n• *Waktu:* 2026-10-02 13:27:16 WIB\n\n👉 Ketik `/ack 19` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 13:27:17
25	20	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #20\n• *Perangkat:* `Router-Edge-01` (192.168.1.3)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 15:09:42 WIB\n\n👉 Ketik `/ack 20` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 15:09:43
26	21	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #21\n• *Perangkat:* `Router-Core-01` (192.168.1.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 15:46:08 WIB\n\n👉 Ketik `/ack 21` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 15:46:09
27	22	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #22\n• *Perangkat:* `Router-Core-01` (192.168.1.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Core-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:04:27 WIB\n\n👉 Ketik `/ack 22` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:04:28
28	\N	-1004429503436	COMMAND_REPLY	Respon /status: Ringkasan telemetri 8 perangkat dikirim ke @darasamsara (UP: 7, DOWN: 1)	SENT	2026-10-02 16:10:44.89848
29	23	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #23\n• *Perangkat:* `Router-Edge-01` (192.168.1.3)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:11:31 WIB\n\n👉 Ketik `/ack 23` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:11:32
30	24	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #24\n• *Perangkat:* `Switch-Dist-01` (192.168.1.2)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Switch-Dist-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:11:48 WIB\n\n👉 Ketik `/ack 24` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:11:48
31	\N	-1004429503436	COMMAND_REPLY	Respon /status: Ringkasan telemetri dikirim ke @Dara Samsara	SENT	2026-10-02 16:12:17.235163
32	25	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #25\n• *Perangkat:* `Router-Backup-01` (192.168.1.254)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Backup-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:12:46 WIB\n\n👉 Ketik `/ack 25` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:12:46
33	26	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #26\n• *Perangkat:* `Router-Edge-01` (192.168.1.3)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:23:46 WIB\n\n👉 Ketik `/ack 26` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:23:47.631766
34	27	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #27\n• *Perangkat:* `Router-Edge-01` (192.168.1.3)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Edge-01 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:25:22 WIB\n\n👉 Ketik `/ack 27` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:25:23.176321
35	28	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #28\n• *Perangkat:* `Router-Branch-Sby` (10.10.20.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Branch-Sby mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:25:33 WIB\n\n👉 Ketik `/ack 28` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:25:34.189349
36	\N	-1004429503436	COMMAND_REPLY	Respon /status: Ringkasan telemetri dikirim ke @Dara Samsara	SENT	2026-10-02 16:27:02.277898
37	\N	-1004429503436	COMMAND_REPLY	Respon /devices: Inventaris node dikirim ke @Dara Samsara	SENT	2026-10-02 16:27:07.624368
38	\N	-1004429503436	COMMAND_REPLY	Respon /device: Detail telemetri RTR-Core-01 dikirim ke @Dara Samsara	SENT	2026-10-02 16:27:19.40363
39	\N	-1004429503436	COMMAND_REPLY	Backup konfigurasi manual RTR-Core-01 berhasil dieksekusi oleh @Dara Samsara.	SENT	2026-10-02 16:28:18.696532
40	29	-1004429503436	ALERT_NOTIFICATION	🚨 *[NOC AGIVA - ALERT SIMULASI]* 🚨\n\n• *Alert ID:* #29\n• *Perangkat:* `Router-Distribution-02` (10.10.10.1)\n• *Severity:* WARNING\n• *Pesan:* Simulasi alert: CPU spike terdeteksi di Router-Distribution-02 mencapai 88.5%.\n• *Waktu:* 2026-10-02 16:53:17 WIB\n\n👉 Ketik `/ack 29` di bot untuk konfirmasi penanganan.	SENT	2026-10-02 16:53:18.441847
41	\N	-1004429503436	COMMAND_REPLY	Respon /start: Dashboard utama dibuka oleh @Dara Samsara	SENT	2026-10-05 13:43:00.560283
42	\N	-1004429503436	COMMAND_REPLY	Respon /devices: Inventaris node dikirim ke @Dara Samsara	SENT	2026-10-05 13:43:33.797489
43	\N	-1004429503436	COMMAND_REPLY	Respon /device: Detail telemetri RTR-Core-01 dikirim ke @Dara Samsara	SENT	2026-10-05 13:44:11.213909
44	\N	-1004429503436	COMMAND_REPLY	Respon /alerts: Daftar gangguan dikirim ke @Dara Samsara	SENT	2026-10-05 13:44:46.266382
45	\N	-1004429503436	COMMAND_REPLY	Alert #ALT-101 (RTR-Branch-BDG) berhasil di-acknowledge oleh @Dara Samsara.	SENT	2026-10-05 13:46:01.06467
46	\N	-1004429503436	COMMAND_REPLY	Respon /help: Panduan bot dikirim ke @Dara Samsara	SENT	2026-10-05 14:59:02.539705
47	\N	-1004429503436	COMMAND_REPLY	Respon /start: Dashboard utama dibuka oleh @Dara Samsara	SENT	2026-10-06 14:54:28.137256
48	\N	-1004429503436	FALLBACK_REPLY	Pesan bebas dari @Dara Samsara → ringkasan status dikirim	SENT	2026-10-06 15:02:46.929475
49	\N	-1004429503436	COMMAND_REPLY	Respon /devices: Inventaris node dikirim ke @Dara Samsara	SENT	2026-10-06 15:03:02.713632
50	\N	-1004429503436	COMMAND_REPLY	Respon /alerts: Daftar gangguan dikirim ke @Dara Samsara	SENT	2026-10-06 15:03:06.816959
51	\N	-1004429503436	COMMAND_REPLY	Respon /help: Panduan bot dikirim ke @Dara Samsara	SENT	2026-10-06 15:03:19.732303
52	\N	-1004429503436	COMMAND_REPLY	Respon /help: Panduan bot dikirim ke @Dara Samsara	SENT	2026-10-06 15:04:31.259882
53	\N	-1004429503436	FALLBACK_REPLY	Pesan bebas dari @Dara Samsara → ringkasan status dikirim	SENT	2026-10-06 15:07:16.629947
54	\N	-1004429503436	COMMAND_REPLY	Respon /help: Panduan bot dikirim ke @Dara Samsara	SENT	2026-10-06 15:07:30.40174
\.


--
-- Data for Name: telegram_whitelist; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.telegram_whitelist (id, chat_id, telegram_username, engineer_name, role, is_active, registered_at) FROM stdin;
1	-1004429503436	@Agiva_Network_Automation_Bot	Agiva Network Automation Channel	Broadcast Group	t	2026-10-01 08:00:00
2	5419251159	@darasamsara	Dara Samsara	Admin	t	2026-10-01 08:05:00
\.


--
-- Name: alerts_alert_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.alerts_alert_id_seq', 29, true);


--
-- Name: backup_history_backup_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.backup_history_backup_id_seq', 4, true);


--
-- Name: device_status_logs_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_status_logs_log_id_seq', 72, true);


--
-- Name: devices_device_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.devices_device_id_seq', 8, true);


--
-- Name: telegram_message_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.telegram_message_logs_id_seq', 54, true);


--
-- Name: telegram_whitelist_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.telegram_whitelist_id_seq', 2, true);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (alert_id);


--
-- Name: backup_history backup_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.backup_history
    ADD CONSTRAINT backup_history_pkey PRIMARY KEY (backup_id);


--
-- Name: device_status_logs device_status_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_status_logs
    ADD CONSTRAINT device_status_logs_pkey PRIMARY KEY (log_id);


--
-- Name: devices devices_ip_address_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_ip_address_key UNIQUE (ip_address);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (device_id);


--
-- Name: telegram_message_logs telegram_message_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_message_logs
    ADD CONSTRAINT telegram_message_logs_pkey PRIMARY KEY (id);


--
-- Name: telegram_whitelist telegram_whitelist_chat_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_whitelist
    ADD CONSTRAINT telegram_whitelist_chat_id_key UNIQUE (chat_id);


--
-- Name: telegram_whitelist telegram_whitelist_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_whitelist
    ADD CONSTRAINT telegram_whitelist_pkey PRIMARY KEY (id);


--
-- Name: alerts alerts_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(device_id) ON DELETE CASCADE;


--
-- Name: backup_history backup_history_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.backup_history
    ADD CONSTRAINT backup_history_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(device_id) ON DELETE CASCADE;


--
-- Name: device_status_logs device_status_logs_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_status_logs
    ADD CONSTRAINT device_status_logs_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.devices(device_id) ON DELETE CASCADE;


--
-- Name: telegram_message_logs telegram_message_logs_alert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.telegram_message_logs
    ADD CONSTRAINT telegram_message_logs_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(alert_id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict ekVmEIzLdKMVYf4ahkGMEYRNCGnb0T58dQ1qyeOxMAYpDVseV6FdY5jkG132kDC

