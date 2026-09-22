

--
-- Name: file_object_sha256_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX file_object_sha256_idx ON assets.file_object USING btree (sha256);



--
-- Name: file_object_status_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX file_object_status_idx ON assets.file_object USING btree (storage_status, scan_status);



--
-- Name: material_applicability_prod_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX material_applicability_prod_idx ON assets.material_applicability USING btree (product_id, variant_id, verified);



--
-- Name: material_applicability_rev_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX material_applicability_rev_idx ON assets.material_applicability USING btree (revision_id);



--
-- Name: material_applicability_scope_key; Type: INDEX; Schema: assets; Owner: -
--

CREATE UNIQUE INDEX material_applicability_scope_key ON assets.material_applicability USING btree (revision_id, product_id, variant_id) NULLS NOT DISTINCT;



--
-- Name: material_revision_file_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX material_revision_file_idx ON assets.material_revision USING btree (file_object_id);



--
-- Name: material_revision_mat_status_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX material_revision_mat_status_idx ON assets.material_revision USING btree (material_id, status);



--
-- Name: product_material_source_idx; Type: INDEX; Schema: assets; Owner: -
--

CREATE INDEX product_material_source_idx ON assets.product_material USING btree (source_id, material_type, status);



--
-- Name: offer_merchant_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX offer_merchant_idx ON catalog.offer USING btree (merchant_id);



--
-- Name: offer_obs_offer_observed_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX offer_obs_offer_observed_idx ON catalog.offer_observation USING btree (offer_id, observed_at DESC);



--
-- Name: offer_obs_source_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX offer_obs_source_idx ON catalog.offer_observation USING btree (source_id);



--
-- Name: offer_variant_status_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX offer_variant_status_idx ON catalog.offer USING btree (variant_id, status);



--
-- Name: product_brand_model_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX product_brand_model_idx ON catalog.product USING btree (brand, model);



--
-- Name: product_category_parent_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX product_category_parent_idx ON catalog.product_category USING btree (parent_id);



--
-- Name: product_fact_evidence_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX product_fact_evidence_idx ON catalog.product_fact USING btree (evidence_id);



--
-- Name: product_fact_prod_attr_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX product_fact_prod_attr_idx ON catalog.product_fact USING btree (product_id, attribute_key, status);



--
-- Name: product_type_status_idx; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX product_type_status_idx ON catalog.product USING btree (product_type, status);



--
-- Name: product_variant_gtin_key; Type: INDEX; Schema: catalog; Owner: -
--

CREATE UNIQUE INDEX product_variant_gtin_key ON catalog.product_variant USING btree (gtin) WHERE (gtin IS NOT NULL);



--
-- Name: pc_build_component_variant_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX pc_build_component_variant_idx ON community.pc_build_component USING btree (variant_id, build_version_id);



--
-- Name: pc_build_owner_updated_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX pc_build_owner_updated_idx ON community.pc_build USING btree (owner_user_id, updated_at DESC);



--
-- Name: pc_build_version_source_plan_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX pc_build_version_source_plan_idx ON community.pc_build_version USING btree (source_plan_revision_id);



--
-- Name: review_author_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX review_author_idx ON community.review USING btree (author_user_id);



--
-- Name: review_revision_domain_ver_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX review_revision_domain_ver_idx ON community.review_revision USING btree (domain_version_id);



--
-- Name: review_revision_review_no_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX review_revision_review_no_idx ON community.review_revision USING btree (review_id, revision_no DESC);



--
-- Name: review_subject_status_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX review_subject_status_idx ON community.review USING btree (subject_id, status, created_at DESC);



--
-- Name: feedback_event_plan_time_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX feedback_event_plan_time_idx ON engine.feedback_event USING btree (plan_id, occurred_at);



--
-- Name: feedback_event_rec_run_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX feedback_event_rec_run_idx ON engine.feedback_event USING btree (recommendation_run_id);



--
-- Name: feedback_event_revision_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX feedback_event_revision_idx ON engine.feedback_event USING btree (revision_id);



--
-- Name: feedback_event_type_time_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX feedback_event_type_time_idx ON engine.feedback_event USING btree (event_type, occurred_at);



--
-- Name: rec_cand_requirement_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX rec_cand_requirement_idx ON engine.recommendation_candidate USING btree (requirement_id);



--
-- Name: rec_cand_run_result_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX rec_cand_run_result_idx ON engine.recommendation_candidate USING btree (run_id, result);



--
-- Name: rec_cand_variant_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX rec_cand_variant_idx ON engine.recommendation_candidate USING btree (variant_id);



--
-- Name: rec_run_domain_ver_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX rec_run_domain_ver_idx ON engine.recommendation_run USING btree (domain_version_id);



--
-- Name: rec_run_revision_created_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX rec_run_revision_created_idx ON engine.recommendation_run USING btree (revision_id, created_at DESC);



--
-- Name: validation_result_run_status_idx; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX validation_result_run_status_idx ON engine.validation_result USING btree (run_id, status);



--
-- Name: evidence_retrieval_hit_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX evidence_retrieval_hit_idx ON evidence.evidence USING btree (retrieval_hit_id);



--
-- Name: evidence_review_aggregate_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX evidence_review_aggregate_idx ON evidence.evidence USING btree (review_aggregate_id);



--
-- Name: evidence_source_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX evidence_source_idx ON evidence.evidence USING btree (source_id);



--
-- Name: evidence_status_valid_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX evidence_status_valid_idx ON evidence.evidence USING btree (status, valid_until);



--
-- Name: ram_summary_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX ram_summary_idx ON evidence.review_aggregate_member USING btree (summary_id);



--
-- Name: review_aggregate_domain_ver_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_aggregate_domain_ver_idx ON evidence.review_aggregate USING btree (domain_version_id);



--
-- Name: review_aggregate_subject_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_aggregate_subject_idx ON evidence.review_aggregate USING btree (subject_id, source_scope, status, window_end DESC);



--
-- Name: review_subject_build_ver_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_subject_build_ver_key ON evidence.review_subject USING btree (build_version_id) WHERE (build_version_id IS NOT NULL);



--
-- Name: review_subject_offer_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_subject_offer_key ON evidence.review_subject USING btree (offer_id) WHERE (offer_id IS NOT NULL);



--
-- Name: review_subject_product_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_subject_product_key ON evidence.review_subject USING btree (product_id) WHERE (product_id IS NOT NULL);



--
-- Name: review_subject_variant_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_subject_variant_key ON evidence.review_subject USING btree (variant_id) WHERE (variant_id IS NOT NULL);



--
-- Name: review_summary_author_ref_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_summary_author_ref_idx ON evidence.review_summary USING btree (author_ref) WHERE (author_ref IS NOT NULL);



--
-- Name: review_summary_external_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_summary_external_key ON evidence.review_summary USING btree (source_id, external_review_key, processing_version) WHERE (external_review_key IS NOT NULL);



--
-- Name: review_summary_internal_key; Type: INDEX; Schema: evidence; Owner: -
--

CREATE UNIQUE INDEX review_summary_internal_key ON evidence.review_summary USING btree (review_revision_id, processing_version) WHERE (review_revision_id IS NOT NULL);



--
-- Name: review_summary_source_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_summary_source_idx ON evidence.review_summary USING btree (source_id);



--
-- Name: review_summary_subject_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_summary_subject_idx ON evidence.review_summary USING btree (subject_id, status, cleaning_status);



--
-- Name: review_summary_subject_posted_idx; Type: INDEX; Schema: evidence; Owner: -
--

CREATE INDEX review_summary_subject_posted_idx ON evidence.review_summary USING btree (subject_id, review_posted_at) WHERE (review_posted_at IS NOT NULL);



--
-- Name: conversation_user_created_idx; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX conversation_user_created_idx ON identity.conversation USING btree (user_id, created_at DESC);



--
-- Name: message_conv_created_idx; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX message_conv_created_idx ON identity.message USING btree (conversation_id, created_at);



--
-- Name: price_watch_active_scope_key; Type: INDEX; Schema: notification; Owner: -
--

CREATE UNIQUE INDEX price_watch_active_scope_key ON notification.price_watch USING btree (revision_id, purchase_line_id) NULLS NOT DISTINCT WHERE (state = 'active'::text);



--
-- Name: price_watch_revision_idx; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX price_watch_revision_idx ON notification.price_watch USING btree (revision_id);



--
-- Name: price_watch_state_ends_idx; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX price_watch_state_ends_idx ON notification.price_watch USING btree (state, ends_at);



--
-- Name: plan_condition_active_key; Type: INDEX; Schema: planning; Owner: -
--

CREATE UNIQUE INDEX plan_condition_active_key ON planning.plan_condition USING btree (revision_id, condition_key) WHERE (status = 'active'::text);



--
-- Name: plan_condition_message_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_condition_message_idx ON planning.plan_condition USING btree (source_message_id);



--
-- Name: plan_condition_rev_status_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_condition_rev_status_idx ON planning.plan_condition USING btree (revision_id, status);



--
-- Name: plan_node_rev_parent_pos_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_node_rev_parent_pos_idx ON planning.plan_node USING btree (revision_id, parent_id, "position");



--
-- Name: plan_owner_updated_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_owner_updated_idx ON planning.plan USING btree (owner_user_id, updated_at DESC);



--
-- Name: plan_revision_domain_ver_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_revision_domain_ver_idx ON planning.plan_revision USING btree (domain_version_id);



--
-- Name: plan_revision_plan_state_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX plan_revision_plan_state_idx ON planning.plan_revision USING btree (plan_id, state);



--
-- Name: purchase_line_offer_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX purchase_line_offer_idx ON planning.purchase_line USING btree (offer_id);



--
-- Name: purchase_line_rev_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX purchase_line_rev_idx ON planning.purchase_line USING btree (revision_id);



--
-- Name: requirement_node_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX requirement_node_idx ON planning.requirement USING btree (node_id, revision_id);



--
-- Name: requirement_rev_status_idx; Type: INDEX; Schema: planning; Owner: -
--

CREATE INDEX requirement_rev_status_idx ON planning.requirement USING btree (revision_id, status);

