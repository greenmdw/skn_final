

--
-- Name: file_object set_updated_at; Type: TRIGGER; Schema: assets; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON assets.file_object FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: material_applicability set_updated_at; Type: TRIGGER; Schema: assets; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON assets.material_applicability FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: material_revision set_updated_at; Type: TRIGGER; Schema: assets; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON assets.material_revision FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: product_material set_updated_at; Type: TRIGGER; Schema: assets; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON assets.product_material FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: case_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.case_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: cooler_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.cooler_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: cpu_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.cpu_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: gpu_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.gpu_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: mainboard_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.mainboard_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: merchant set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.merchant FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: offer set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.offer FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: product set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.product FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: product_category set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.product_category FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: product_fact set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.product_fact FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: product_variant set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.product_variant FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: psu_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.psu_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: ram_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.ram_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: ssd_spec set_updated_at; Type: TRIGGER; Schema: catalog; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON catalog.ssd_spec FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: pc_build set_updated_at; Type: TRIGGER; Schema: community; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.pc_build FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: pc_build_version set_updated_at; Type: TRIGGER; Schema: community; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.pc_build_version FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: review set_updated_at; Type: TRIGGER; Schema: community; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.review FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: review_revision set_updated_at; Type: TRIGGER; Schema: community; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON community.review_revision FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: domain set_updated_at; Type: TRIGGER; Schema: config; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON config.domain FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: recommendation_candidate set_updated_at; Type: TRIGGER; Schema: engine; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON engine.recommendation_candidate FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: recommendation_run set_updated_at; Type: TRIGGER; Schema: engine; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON engine.recommendation_run FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: evidence set_updated_at; Type: TRIGGER; Schema: evidence; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON evidence.evidence FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: review_aggregate set_updated_at; Type: TRIGGER; Schema: evidence; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON evidence.review_aggregate FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: review_subject set_updated_at; Type: TRIGGER; Schema: evidence; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON evidence.review_subject FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: review_summary set_updated_at; Type: TRIGGER; Schema: evidence; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON evidence.review_summary FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: source set_updated_at; Type: TRIGGER; Schema: evidence; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON evidence.source FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: app_user set_updated_at; Type: TRIGGER; Schema: identity; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON identity.app_user FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: price_watch set_updated_at; Type: TRIGGER; Schema: notification; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON notification.price_watch FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: plan set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.plan FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: plan_condition set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.plan_condition FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: plan_node set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.plan_node FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: plan_revision set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.plan_revision FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: purchase_line set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.purchase_line FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();



--
-- Name: requirement set_updated_at; Type: TRIGGER; Schema: planning; Owner: -
--

CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.requirement FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

