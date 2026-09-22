
--
-- Name: file_object file_object_bucket_key_ver_key; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.file_object
    ADD CONSTRAINT file_object_bucket_key_ver_key UNIQUE (bucket, object_key, storage_version);



--
-- Name: file_object file_object_pkey; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.file_object
    ADD CONSTRAINT file_object_pkey PRIMARY KEY (id);



--
-- Name: material_applicability material_applicability_pkey; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_applicability
    ADD CONSTRAINT material_applicability_pkey PRIMARY KEY (id);



--
-- Name: material_revision material_revision_id_mat_key; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_revision
    ADD CONSTRAINT material_revision_id_mat_key UNIQUE (id, material_id);



--
-- Name: material_revision material_revision_mat_no_key; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_revision
    ADD CONSTRAINT material_revision_mat_no_key UNIQUE (material_id, revision_no);



--
-- Name: material_revision material_revision_pkey; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_revision
    ADD CONSTRAINT material_revision_pkey PRIMARY KEY (id);



--
-- Name: product_material product_material_pkey; Type: CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.product_material
    ADD CONSTRAINT product_material_pkey PRIMARY KEY (id);



--
-- Name: case_spec case_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.case_spec
    ADD CONSTRAINT case_spec_pkey PRIMARY KEY (product_id);



--
-- Name: cooler_spec cooler_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cooler_spec
    ADD CONSTRAINT cooler_spec_pkey PRIMARY KEY (product_id);



--
-- Name: cpu_spec cpu_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cpu_spec
    ADD CONSTRAINT cpu_spec_pkey PRIMARY KEY (product_id);



--
-- Name: gpu_spec gpu_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.gpu_spec
    ADD CONSTRAINT gpu_spec_pkey PRIMARY KEY (product_id);



--
-- Name: keyboard_spec keyboard_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.keyboard_spec
    ADD CONSTRAINT keyboard_spec_pkey PRIMARY KEY (product_id);



--
-- Name: mainboard_spec mainboard_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.mainboard_spec
    ADD CONSTRAINT mainboard_spec_pkey PRIMARY KEY (product_id);



--
-- Name: merchant merchant_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.merchant
    ADD CONSTRAINT merchant_pkey PRIMARY KEY (id);



--
-- Name: merchant merchant_platform_seller_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.merchant
    ADD CONSTRAINT merchant_platform_seller_key UNIQUE (platform, external_seller_id);



--
-- Name: monitor_spec monitor_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.monitor_spec
    ADD CONSTRAINT monitor_spec_pkey PRIMARY KEY (product_id);



--
-- Name: mouse_spec mouse_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.mouse_spec
    ADD CONSTRAINT mouse_spec_pkey PRIMARY KEY (product_id);



--
-- Name: offer offer_merchant_ext_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer
    ADD CONSTRAINT offer_merchant_ext_key UNIQUE (merchant_id, external_offer_id);



--
-- Name: offer_observation offer_obs_id_offer_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer_observation
    ADD CONSTRAINT offer_obs_id_offer_key UNIQUE (id, offer_id);



--
-- Name: offer_observation offer_observation_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer_observation
    ADD CONSTRAINT offer_observation_pkey PRIMARY KEY (id);



--
-- Name: offer offer_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer
    ADD CONSTRAINT offer_pkey PRIMARY KEY (id);



--
-- Name: peripheral_price_snapshot peripheral_price_snapshot_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.peripheral_price_snapshot
    ADD CONSTRAINT peripheral_price_snapshot_pkey PRIMARY KEY (product_id);



--
-- Name: product_category product_category_code_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_category
    ADD CONSTRAINT product_category_code_key UNIQUE (code);



--
-- Name: product_category product_category_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_category
    ADD CONSTRAINT product_category_pkey PRIMARY KEY (id);



--
-- Name: product_fact product_fact_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_fact
    ADD CONSTRAINT product_fact_pkey PRIMARY KEY (id);



--
-- Name: product product_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product
    ADD CONSTRAINT product_pkey PRIMARY KEY (id);



--
-- Name: product_variant product_variant_id_prod_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_variant
    ADD CONSTRAINT product_variant_id_prod_key UNIQUE (id, product_id);



--
-- Name: product_variant product_variant_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_variant
    ADD CONSTRAINT product_variant_pkey PRIMARY KEY (id);



--
-- Name: product_variant product_variant_prod_key_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_variant
    ADD CONSTRAINT product_variant_prod_key_key UNIQUE (product_id, variant_key);



--
-- Name: psu_spec psu_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.psu_spec
    ADD CONSTRAINT psu_spec_pkey PRIMARY KEY (product_id);



--
-- Name: ram_spec ram_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ram_spec
    ADD CONSTRAINT ram_spec_pkey PRIMARY KEY (product_id);



--
-- Name: speaker_spec speaker_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.speaker_spec
    ADD CONSTRAINT speaker_spec_pkey PRIMARY KEY (product_id);



--
-- Name: ssd_spec ssd_spec_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ssd_spec
    ADD CONSTRAINT ssd_spec_pkey PRIMARY KEY (product_id);



--
-- Name: pc_build_component pc_build_component_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_component
    ADD CONSTRAINT pc_build_component_pkey PRIMARY KEY (id);



--
-- Name: pc_build_component pc_build_component_slot_pos_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_component
    ADD CONSTRAINT pc_build_component_slot_pos_key UNIQUE (build_version_id, slot_key, "position");



--
-- Name: pc_build pc_build_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build
    ADD CONSTRAINT pc_build_pkey PRIMARY KEY (id);



--
-- Name: pc_build_version pc_build_version_build_no_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_version
    ADD CONSTRAINT pc_build_version_build_no_key UNIQUE (build_id, version_no);



--
-- Name: pc_build_version pc_build_version_id_build_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_version
    ADD CONSTRAINT pc_build_version_id_build_key UNIQUE (id, build_id);



--
-- Name: pc_build_version pc_build_version_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_version
    ADD CONSTRAINT pc_build_version_pkey PRIMARY KEY (id);



--
-- Name: review review_author_subject_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review
    ADD CONSTRAINT review_author_subject_key UNIQUE (author_user_id, subject_id);



--
-- Name: review review_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review
    ADD CONSTRAINT review_pkey PRIMARY KEY (id);



--
-- Name: review_revision review_revision_id_review_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review_revision
    ADD CONSTRAINT review_revision_id_review_key UNIQUE (id, review_id);



--
-- Name: review_revision review_revision_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review_revision
    ADD CONSTRAINT review_revision_pkey PRIMARY KEY (id);



--
-- Name: review_revision review_revision_review_no_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review_revision
    ADD CONSTRAINT review_revision_review_no_key UNIQUE (review_id, revision_no);



--
-- Name: domain domain_code_key; Type: CONSTRAINT; Schema: config; Owner: -
--

ALTER TABLE ONLY config.domain
    ADD CONSTRAINT domain_code_key UNIQUE (code);



--
-- Name: domain domain_pkey; Type: CONSTRAINT; Schema: config; Owner: -
--

ALTER TABLE ONLY config.domain
    ADD CONSTRAINT domain_pkey PRIMARY KEY (id);



--
-- Name: domain_version domain_version_domain_no_key; Type: CONSTRAINT; Schema: config; Owner: -
--

ALTER TABLE ONLY config.domain_version
    ADD CONSTRAINT domain_version_domain_no_key UNIQUE (domain_id, version_no);



--
-- Name: domain_version domain_version_pkey; Type: CONSTRAINT; Schema: config; Owner: -
--

ALTER TABLE ONLY config.domain_version
    ADD CONSTRAINT domain_version_pkey PRIMARY KEY (id);



--
-- Name: feedback_event feedback_event_key_key; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_key_key UNIQUE (event_key);



--
-- Name: feedback_event feedback_event_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_pkey PRIMARY KEY (id);



--
-- Name: recommendation_candidate recommendation_candidate_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_candidate
    ADD CONSTRAINT recommendation_candidate_pkey PRIMARY KEY (id);



--
-- Name: recommendation_run recommendation_run_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_run
    ADD CONSTRAINT recommendation_run_pkey PRIMARY KEY (id);



--
-- Name: validation_result validation_result_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.validation_result
    ADD CONSTRAINT validation_result_pkey PRIMARY KEY (id);



--
-- Name: evidence evidence_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.evidence
    ADD CONSTRAINT evidence_pkey PRIMARY KEY (id);



--
-- Name: review_aggregate_member review_aggregate_member_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate_member
    ADD CONSTRAINT review_aggregate_member_pkey PRIMARY KEY (aggregate_id, summary_id);



--
-- Name: review_aggregate review_aggregate_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate
    ADD CONSTRAINT review_aggregate_pkey PRIMARY KEY (id);



--
-- Name: review_subject review_subject_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_subject
    ADD CONSTRAINT review_subject_pkey PRIMARY KEY (id);



--
-- Name: review_summary review_summary_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_summary
    ADD CONSTRAINT review_summary_pkey PRIMARY KEY (id);



--
-- Name: source source_pkey; Type: CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.source
    ADD CONSTRAINT source_pkey PRIMARY KEY (id);



--
-- Name: app_user app_user_auth_subject_key; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.app_user
    ADD CONSTRAINT app_user_auth_subject_key UNIQUE (auth_subject);



--
-- Name: app_user app_user_email_key; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.app_user
    ADD CONSTRAINT app_user_email_key UNIQUE (email_normalized);



--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);



--
-- Name: conversation conversation_pkey; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.conversation
    ADD CONSTRAINT conversation_pkey PRIMARY KEY (id);



--
-- Name: message message_conv_client_key; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.message
    ADD CONSTRAINT message_conv_client_key UNIQUE (conversation_id, client_message_id);



--
-- Name: message message_pkey; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.message
    ADD CONSTRAINT message_pkey PRIMARY KEY (id);



--
-- Name: price_watch price_watch_pkey; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.price_watch
    ADD CONSTRAINT price_watch_pkey PRIMARY KEY (id);



--
-- Name: plan_condition plan_condition_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_condition
    ADD CONSTRAINT plan_condition_pkey PRIMARY KEY (id);



--
-- Name: plan plan_conversation_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan
    ADD CONSTRAINT plan_conversation_key UNIQUE (conversation_id);



--
-- Name: plan_node plan_node_id_rev_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_node
    ADD CONSTRAINT plan_node_id_rev_key UNIQUE (id, revision_id);



--
-- Name: plan_node plan_node_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_node
    ADD CONSTRAINT plan_node_pkey PRIMARY KEY (id);



--
-- Name: plan plan_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan
    ADD CONSTRAINT plan_pkey PRIMARY KEY (id);



--
-- Name: plan_revision plan_revision_id_plan_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_revision
    ADD CONSTRAINT plan_revision_id_plan_key UNIQUE (id, plan_id);



--
-- Name: plan_revision plan_revision_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_revision
    ADD CONSTRAINT plan_revision_pkey PRIMARY KEY (id);



--
-- Name: plan_revision plan_revision_plan_no_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_revision
    ADD CONSTRAINT plan_revision_plan_no_key UNIQUE (plan_id, revision_no);



--
-- Name: purchase_line purchase_line_id_rev_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.purchase_line
    ADD CONSTRAINT purchase_line_id_rev_key UNIQUE (id, revision_id);



--
-- Name: purchase_line purchase_line_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.purchase_line
    ADD CONSTRAINT purchase_line_pkey PRIMARY KEY (id);



--
-- Name: requirement requirement_id_rev_key; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.requirement
    ADD CONSTRAINT requirement_id_rev_key UNIQUE (id, revision_id);



--
-- Name: requirement requirement_pkey; Type: CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.requirement
    ADD CONSTRAINT requirement_pkey PRIMARY KEY (id);



--
-- Name: file_object file_object_uploaded_by_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.file_object
    ADD CONSTRAINT file_object_uploaded_by_fk FOREIGN KEY (uploaded_by) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: material_applicability material_applicability_product_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_applicability
    ADD CONSTRAINT material_applicability_product_fk FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE RESTRICT;



--
-- Name: material_applicability material_applicability_revision_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_applicability
    ADD CONSTRAINT material_applicability_revision_fk FOREIGN KEY (revision_id) REFERENCES assets.material_revision(id) ON DELETE RESTRICT;



--
-- Name: material_applicability material_applicability_variant_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_applicability
    ADD CONSTRAINT material_applicability_variant_fk FOREIGN KEY (variant_id, product_id) REFERENCES catalog.product_variant(id, product_id) ON DELETE RESTRICT;



--
-- Name: material_revision material_revision_file_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_revision
    ADD CONSTRAINT material_revision_file_fk FOREIGN KEY (file_object_id) REFERENCES assets.file_object(id) ON DELETE RESTRICT;



--
-- Name: material_revision material_revision_material_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.material_revision
    ADD CONSTRAINT material_revision_material_fk FOREIGN KEY (material_id) REFERENCES assets.product_material(id) ON DELETE RESTRICT;



--
-- Name: product_material product_material_current_revision_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.product_material
    ADD CONSTRAINT product_material_current_revision_fk FOREIGN KEY (current_revision_id, id) REFERENCES assets.material_revision(id, material_id) ON DELETE RESTRICT;



--
-- Name: product_material product_material_source_fk; Type: FK CONSTRAINT; Schema: assets; Owner: -
--

ALTER TABLE ONLY assets.product_material
    ADD CONSTRAINT product_material_source_fk FOREIGN KEY (source_id) REFERENCES evidence.source(id) ON DELETE RESTRICT;



--
-- Name: case_spec case_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.case_spec
    ADD CONSTRAINT case_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: cooler_spec cooler_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cooler_spec
    ADD CONSTRAINT cooler_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: cpu_spec cpu_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cpu_spec
    ADD CONSTRAINT cpu_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: gpu_spec gpu_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.gpu_spec
    ADD CONSTRAINT gpu_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: keyboard_spec keyboard_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.keyboard_spec
    ADD CONSTRAINT keyboard_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: mainboard_spec mainboard_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.mainboard_spec
    ADD CONSTRAINT mainboard_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: monitor_spec monitor_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.monitor_spec
    ADD CONSTRAINT monitor_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: mouse_spec mouse_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.mouse_spec
    ADD CONSTRAINT mouse_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: offer offer_merchant_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer
    ADD CONSTRAINT offer_merchant_fk FOREIGN KEY (merchant_id) REFERENCES catalog.merchant(id) ON DELETE RESTRICT;



--
-- Name: offer_observation offer_obs_offer_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer_observation
    ADD CONSTRAINT offer_obs_offer_fk FOREIGN KEY (offer_id) REFERENCES catalog.offer(id) ON DELETE RESTRICT;



--
-- Name: offer_observation offer_obs_source_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer_observation
    ADD CONSTRAINT offer_obs_source_fk FOREIGN KEY (source_id) REFERENCES evidence.source(id) ON DELETE RESTRICT;



--
-- Name: offer offer_variant_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.offer
    ADD CONSTRAINT offer_variant_fk FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id) ON DELETE RESTRICT;



--
-- Name: peripheral_price_snapshot peripheral_price_snapshot_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.peripheral_price_snapshot
    ADD CONSTRAINT peripheral_price_snapshot_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: product product_category_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product
    ADD CONSTRAINT product_category_fk FOREIGN KEY (category_id) REFERENCES catalog.product_category(id) ON DELETE RESTRICT;



--
-- Name: product_category product_category_parent_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_category
    ADD CONSTRAINT product_category_parent_fk FOREIGN KEY (parent_id) REFERENCES catalog.product_category(id) ON DELETE RESTRICT;



--
-- Name: product_fact product_fact_evidence_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_fact
    ADD CONSTRAINT product_fact_evidence_fk FOREIGN KEY (evidence_id) REFERENCES evidence.evidence(id) ON DELETE RESTRICT;



--
-- Name: product_fact product_fact_product_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_fact
    ADD CONSTRAINT product_fact_product_fk FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE RESTRICT;



--
-- Name: product_fact product_fact_variant_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_fact
    ADD CONSTRAINT product_fact_variant_fk FOREIGN KEY (variant_id, product_id) REFERENCES catalog.product_variant(id, product_id) ON DELETE RESTRICT;



--
-- Name: product_variant product_variant_product_fk; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.product_variant
    ADD CONSTRAINT product_variant_product_fk FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE RESTRICT;



--
-- Name: psu_spec psu_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.psu_spec
    ADD CONSTRAINT psu_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: ram_spec ram_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ram_spec
    ADD CONSTRAINT ram_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: speaker_spec speaker_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.speaker_spec
    ADD CONSTRAINT speaker_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: ssd_spec ssd_spec_product_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.ssd_spec
    ADD CONSTRAINT ssd_spec_product_id_fkey FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE CASCADE;



--
-- Name: pc_build_component pc_build_component_variant_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_component
    ADD CONSTRAINT pc_build_component_variant_fk FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id) ON DELETE RESTRICT;



--
-- Name: pc_build_component pc_build_component_version_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_component
    ADD CONSTRAINT pc_build_component_version_fk FOREIGN KEY (build_version_id) REFERENCES community.pc_build_version(id) ON DELETE RESTRICT;



--
-- Name: pc_build pc_build_current_version_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build
    ADD CONSTRAINT pc_build_current_version_fk FOREIGN KEY (current_version_id, id) REFERENCES community.pc_build_version(id, build_id) ON DELETE RESTRICT;



--
-- Name: pc_build pc_build_owner_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build
    ADD CONSTRAINT pc_build_owner_fk FOREIGN KEY (owner_user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: pc_build_version pc_build_version_build_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_version
    ADD CONSTRAINT pc_build_version_build_fk FOREIGN KEY (build_id) REFERENCES community.pc_build(id) ON DELETE RESTRICT;



--
-- Name: pc_build_version pc_build_version_source_plan_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.pc_build_version
    ADD CONSTRAINT pc_build_version_source_plan_fk FOREIGN KEY (source_plan_revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: review review_author_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review
    ADD CONSTRAINT review_author_fk FOREIGN KEY (author_user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: review review_current_revision_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review
    ADD CONSTRAINT review_current_revision_fk FOREIGN KEY (current_revision_id, id) REFERENCES community.review_revision(id, review_id) ON DELETE RESTRICT;



--
-- Name: review_revision review_revision_domain_version_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review_revision
    ADD CONSTRAINT review_revision_domain_version_fk FOREIGN KEY (domain_version_id) REFERENCES config.domain_version(id) ON DELETE RESTRICT;



--
-- Name: review_revision review_revision_review_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review_revision
    ADD CONSTRAINT review_revision_review_fk FOREIGN KEY (review_id) REFERENCES community.review(id) ON DELETE RESTRICT;



--
-- Name: review review_subject_fk; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.review
    ADD CONSTRAINT review_subject_fk FOREIGN KEY (subject_id) REFERENCES evidence.review_subject(id) ON DELETE RESTRICT;



--
-- Name: domain_version domain_version_domain_fk; Type: FK CONSTRAINT; Schema: config; Owner: -
--

ALTER TABLE ONLY config.domain_version
    ADD CONSTRAINT domain_version_domain_fk FOREIGN KEY (domain_id) REFERENCES config.domain(id) ON DELETE RESTRICT;



--
-- Name: feedback_event feedback_event_plan_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_plan_fk FOREIGN KEY (plan_id) REFERENCES planning.plan(id) ON DELETE RESTRICT;



--
-- Name: feedback_event feedback_event_rec_run_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_rec_run_fk FOREIGN KEY (recommendation_run_id) REFERENCES engine.recommendation_run(id) ON DELETE RESTRICT;



--
-- Name: feedback_event feedback_event_revision_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: feedback_event feedback_event_user_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.feedback_event
    ADD CONSTRAINT feedback_event_user_fk FOREIGN KEY (user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: recommendation_candidate rec_cand_observation_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_candidate
    ADD CONSTRAINT rec_cand_observation_fk FOREIGN KEY (offer_observation_id) REFERENCES catalog.offer_observation(id) ON DELETE RESTRICT;



--
-- Name: recommendation_candidate rec_cand_requirement_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_candidate
    ADD CONSTRAINT rec_cand_requirement_fk FOREIGN KEY (requirement_id) REFERENCES planning.requirement(id) ON DELETE RESTRICT;



--
-- Name: recommendation_candidate rec_cand_run_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_candidate
    ADD CONSTRAINT rec_cand_run_fk FOREIGN KEY (run_id) REFERENCES engine.recommendation_run(id) ON DELETE RESTRICT;



--
-- Name: recommendation_candidate rec_cand_variant_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_candidate
    ADD CONSTRAINT rec_cand_variant_fk FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id) ON DELETE RESTRICT;



--
-- Name: recommendation_run rec_run_domain_version_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_run
    ADD CONSTRAINT rec_run_domain_version_fk FOREIGN KEY (domain_version_id) REFERENCES config.domain_version(id) ON DELETE RESTRICT;



--
-- Name: recommendation_run rec_run_revision_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.recommendation_run
    ADD CONSTRAINT rec_run_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: validation_result validation_result_run_fk; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.validation_result
    ADD CONSTRAINT validation_result_run_fk FOREIGN KEY (run_id) REFERENCES engine.recommendation_run(id) ON DELETE RESTRICT;



--
-- Name: evidence evidence_review_aggregate_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.evidence
    ADD CONSTRAINT evidence_review_aggregate_fk FOREIGN KEY (review_aggregate_id) REFERENCES evidence.review_aggregate(id) ON DELETE RESTRICT;



--
-- Name: evidence evidence_source_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.evidence
    ADD CONSTRAINT evidence_source_fk FOREIGN KEY (source_id) REFERENCES evidence.source(id) ON DELETE RESTRICT;



--
-- Name: review_aggregate_member ram_aggregate_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate_member
    ADD CONSTRAINT ram_aggregate_fk FOREIGN KEY (aggregate_id) REFERENCES evidence.review_aggregate(id) ON DELETE RESTRICT;



--
-- Name: review_aggregate_member ram_summary_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate_member
    ADD CONSTRAINT ram_summary_fk FOREIGN KEY (summary_id) REFERENCES evidence.review_summary(id) ON DELETE RESTRICT;



--
-- Name: review_aggregate review_aggregate_domain_version_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate
    ADD CONSTRAINT review_aggregate_domain_version_fk FOREIGN KEY (domain_version_id) REFERENCES config.domain_version(id) ON DELETE RESTRICT;



--
-- Name: review_aggregate review_aggregate_subject_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_aggregate
    ADD CONSTRAINT review_aggregate_subject_fk FOREIGN KEY (subject_id) REFERENCES evidence.review_subject(id) ON DELETE RESTRICT;



--
-- Name: review_subject review_subject_build_version_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_subject
    ADD CONSTRAINT review_subject_build_version_fk FOREIGN KEY (build_version_id) REFERENCES community.pc_build_version(id) ON DELETE RESTRICT;



--
-- Name: review_subject review_subject_offer_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_subject
    ADD CONSTRAINT review_subject_offer_fk FOREIGN KEY (offer_id) REFERENCES catalog.offer(id) ON DELETE RESTRICT;



--
-- Name: review_subject review_subject_product_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_subject
    ADD CONSTRAINT review_subject_product_fk FOREIGN KEY (product_id) REFERENCES catalog.product(id) ON DELETE RESTRICT;



--
-- Name: review_subject review_subject_variant_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_subject
    ADD CONSTRAINT review_subject_variant_fk FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id) ON DELETE RESTRICT;



--
-- Name: review_summary review_summary_revision_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_summary
    ADD CONSTRAINT review_summary_revision_fk FOREIGN KEY (review_revision_id) REFERENCES community.review_revision(id) ON DELETE RESTRICT;



--
-- Name: review_summary review_summary_source_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_summary
    ADD CONSTRAINT review_summary_source_fk FOREIGN KEY (source_id) REFERENCES evidence.source(id) ON DELETE RESTRICT;



--
-- Name: review_summary review_summary_subject_fk; Type: FK CONSTRAINT; Schema: evidence; Owner: -
--

ALTER TABLE ONLY evidence.review_summary
    ADD CONSTRAINT review_summary_subject_fk FOREIGN KEY (subject_id) REFERENCES evidence.review_subject(id) ON DELETE RESTRICT;



--
-- Name: conversation conversation_user_fk; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.conversation
    ADD CONSTRAINT conversation_user_fk FOREIGN KEY (user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: message message_conversation_fk; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.message
    ADD CONSTRAINT message_conversation_fk FOREIGN KEY (conversation_id) REFERENCES identity.conversation(id) ON DELETE RESTRICT;



--
-- Name: price_watch price_watch_purchase_line_fk; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.price_watch
    ADD CONSTRAINT price_watch_purchase_line_fk FOREIGN KEY (purchase_line_id) REFERENCES planning.purchase_line(id) ON DELETE RESTRICT;



--
-- Name: price_watch price_watch_revision_fk; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.price_watch
    ADD CONSTRAINT price_watch_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: plan_condition plan_condition_message_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_condition
    ADD CONSTRAINT plan_condition_message_fk FOREIGN KEY (source_message_id) REFERENCES identity.message(id) ON DELETE RESTRICT;



--
-- Name: plan_condition plan_condition_revision_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_condition
    ADD CONSTRAINT plan_condition_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: plan_condition plan_condition_supersedes_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_condition
    ADD CONSTRAINT plan_condition_supersedes_fk FOREIGN KEY (supersedes_id) REFERENCES planning.plan_condition(id) ON DELETE RESTRICT;



--
-- Name: plan plan_conversation_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan
    ADD CONSTRAINT plan_conversation_fk FOREIGN KEY (conversation_id) REFERENCES identity.conversation(id) ON DELETE RESTRICT;



--
-- Name: plan plan_current_revision_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan
    ADD CONSTRAINT plan_current_revision_fk FOREIGN KEY (current_revision_id, id) REFERENCES planning.plan_revision(id, plan_id) ON DELETE RESTRICT;



--
-- Name: plan_node plan_node_parent_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_node
    ADD CONSTRAINT plan_node_parent_fk FOREIGN KEY (parent_id, revision_id) REFERENCES planning.plan_node(id, revision_id) ON DELETE RESTRICT;



--
-- Name: plan_node plan_node_revision_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_node
    ADD CONSTRAINT plan_node_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: plan plan_owner_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan
    ADD CONSTRAINT plan_owner_fk FOREIGN KEY (owner_user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;



--
-- Name: plan_revision plan_revision_domain_version_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_revision
    ADD CONSTRAINT plan_revision_domain_version_fk FOREIGN KEY (domain_version_id) REFERENCES config.domain_version(id) ON DELETE RESTRICT;



--
-- Name: plan_revision plan_revision_plan_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.plan_revision
    ADD CONSTRAINT plan_revision_plan_fk FOREIGN KEY (plan_id) REFERENCES planning.plan(id) ON DELETE RESTRICT;



--
-- Name: purchase_line purchase_line_observation_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.purchase_line
    ADD CONSTRAINT purchase_line_observation_fk FOREIGN KEY (selected_observation_id, offer_id) REFERENCES catalog.offer_observation(id, offer_id) ON DELETE RESTRICT;



--
-- Name: purchase_line purchase_line_offer_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.purchase_line
    ADD CONSTRAINT purchase_line_offer_fk FOREIGN KEY (offer_id) REFERENCES catalog.offer(id) ON DELETE RESTRICT;



--
-- Name: purchase_line purchase_line_revision_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.purchase_line
    ADD CONSTRAINT purchase_line_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;



--
-- Name: requirement requirement_node_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.requirement
    ADD CONSTRAINT requirement_node_fk FOREIGN KEY (node_id, revision_id) REFERENCES planning.plan_node(id, revision_id) ON DELETE RESTRICT;



--
-- Name: requirement requirement_revision_fk; Type: FK CONSTRAINT; Schema: planning; Owner: -
--

ALTER TABLE ONLY planning.requirement
    ADD CONSTRAINT requirement_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;

