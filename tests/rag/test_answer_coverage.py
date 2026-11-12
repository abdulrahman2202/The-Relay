import pytest

from retrieval.evidence import assess_answer_coverage, infer_answer_parts

A9 = (
    "What probability threshold turns H-Net routing scores into chunk boundaries, "
    "and what boundary probability is forced at the first position?"
)
SOURCE = "bt = 1{pt ≥0.5}, where p1 = 1.0 by definition, ensuring a first boundary."
THRESHOLD = ("The routing threshold is 0.5.", (SOURCE,))
FIRST = ("The first-position boundary probability is 1.0.", (SOURCE,))


def test_threshold_alone_does_not_cover_first_position_even_when_quote_does():
    result = assess_answer_coverage(infer_answer_parts(A9), (THRESHOLD,))
    assert result.status == "incomplete"
    assert result.missing == ("first-position boundary probability",)
    assert not result.unrecognized


def test_duplicates_and_unrelated_numbers_do_not_supply_a_missing_part():
    claims = (THRESHOLD, THRESHOLD, ("Another value is 1.0.", (SOURCE,)))
    result = assess_answer_coverage(infer_answer_parts(A9), claims)
    assert result.missing == ("first-position boundary probability",)


def test_one_claim_can_cover_multiple_parts():
    text = "The routing threshold is 0.5; the first-position boundary probability is 1.0."
    result = assess_answer_coverage(infer_answer_parts(A9), ((text, (SOURCE,)),))
    assert result.status == "complete"
    assert len(result.required) == 2


@pytest.mark.parametrize("value", ["0.25", "0.8", "0.99", "1e-4"])
def test_values_come_from_each_claims_own_evidence_not_expected_answers(value):
    quote = f"bt = 1{{pt >={value}}}; p1 = {value} by definition."
    claims = (
        (f"The routing threshold is {value}.", (quote,)),
        (f"The initial boundary probability is {value}.", (quote,)),
    )
    assert assess_answer_coverage(infer_answer_parts(A9), claims).status == "complete"


def test_coverage_does_not_truncate_a_scientific_notation_value():
    quote = "pt >=1e-4; p1 = 0.8 by definition."
    claims = (
        ("The routing threshold is 1e-3.", (quote,)),
        ("The initial boundary probability is 0.8.", (quote,)),
    )
    result = assess_answer_coverage(infer_answer_parts(A9), claims)
    assert result.missing == ("routing threshold",)


def test_part_value_cannot_borrow_support_from_another_role_or_claim():
    wrong_value = ("The initial boundary probability is 0.5.", (SOURCE,))
    result = assess_answer_coverage(infer_answer_parts(A9), (THRESHOLD, wrong_value))
    assert result.missing == ("first-position boundary probability",)
    no_own_evidence = (FIRST[0], ("bt = 1{pt ≥0.5} is the threshold.",))
    result = assess_answer_coverage(infer_answer_parts(A9), (THRESHOLD, no_own_evidence))
    assert result.missing == ("first-position boundary probability",)


@pytest.mark.parametrize(
    "text",
    [
        "The first-position boundary probability is unknown.",
        "The first-position boundary probability is not 1.0.",
        "Is the first-position boundary probability 1.0?",
    ],
)
def test_questions_and_missing_values_are_not_assertions(text):
    result = assess_answer_coverage(infer_answer_parts(A9), (THRESHOLD, (text, (SOURCE,))))
    assert result.missing == ("first-position boundary probability",)


def test_formula_aliases_and_unicode_subscripts_are_supported():
    claims = (("pt >=0.5.", (SOURCE,)), ("p₁ = 1.0.", (SOURCE,)))
    assert assess_answer_coverage(infer_answer_parts(A9), claims).status == "complete"


def test_shared_latency_noun_requires_both_named_measurements():
    plan = infer_answer_parts("What theoretical and practical latency figures does Moshi report?")
    quote = "Moshi has a theoretical latency of 160ms, 200ms in practice."
    practical = ("Moshi's practical latency is 200 ms.", (quote,))
    result = assess_answer_coverage(plan, (practical,))
    assert result.missing == ("theoretical latency",)
    theoretical = ("Moshi's theoretical latency is 160 ms.", (quote,))
    assert assess_answer_coverage(plan, (theoretical, practical)).status == "complete"


def test_optimizer_hyperparameters_and_warmup_are_separate_requirements():
    plan = infer_answer_parts(
        "Which optimizer and beta values were used to train the Transformer, "
        "and how many learning-rate warmup steps were used?"
    )
    quote = "We used the Adam optimizer with β1 = 0.9, β2 = 0.98. warmup_steps = 4000."
    text = "The Adam optimizer uses beta1 = 0.9, beta2 = 0.98 and 4000 warmup steps."
    assert assess_answer_coverage(plan, ((text, (quote,)),)).status == "complete"
    result = assess_answer_coverage(
        plan, (("The Adam optimizer uses 4000 warmup steps.", (quote,)),)
    )
    assert result.missing == ("beta1", "beta2")


@pytest.mark.parametrize(
    "question",
    [
        A9.rstrip("?") + ", and what is its color?",
        "What is the routing threshold, the first-position probability, and the training cost?",
        "Describe routing behavior and explain its limitations.",
        "What is the latency of Moshi and Helium?",
        "What is the routing threshold together with its explanation?",
        "What is the routing threshold & who invented it?",
        "Compare routing behavior with the earlier model.",
        "What is the routing threshold, and why is the first-position probability forced?",
    ],
)
def test_unrecognized_required_parts_fail_closed(question):
    result = assess_answer_coverage(infer_answer_parts(question), (THRESHOLD, FIRST))
    assert result.status == "unrecognized"
    assert result.unrecognized


@pytest.mark.parametrize(
    "question",
    [
        "Why does scaled dot-product attention divide by the square root of the key dimension?",
        "How does H-Net replace handcrafted tokenization with learned dynamic chunking?",
        "What is the practical latency of Moshi?",
    ],
)
def test_single_requests_keep_the_existing_citation_contract(question):
    plan = infer_answer_parts(question)
    assert not plan.required and not plan.unrecognized
    assert assess_answer_coverage(plan, ()).status == "not_required"


def test_plural_named_parameters_are_parts_even_without_a_conjunction():
    plan = infer_answer_parts("Which beta values were used to train the model?")
    quote = "beta1 = 0.9 and beta2 = 0.98 were used."
    result = assess_answer_coverage(plan, (("beta1 = 0.9.", (quote,)),))
    assert result.missing == ("beta2",)


@pytest.mark.parametrize(
    "question, quote, text",
    [
        (
            "How many attention heads does the Transformer base model use, "
            "and what are the per-head key and value dimensions?",
            "We employ h = 8 parallel attention layers, or heads. dk = dv = dmodel/h = 64.",
            "The model uses 8 attention heads; key and value dimensions are 64.",
        ),
        (
            "How many quantizers and codebook entries does Mimi use, "
            "and what frame rate and bitrate result?",
            "We use Q = 8 quantizers with a codebook size of NA = 2048. "
            "At 12.5Hz this represents a bitrate of 1.1kbps.",
            "Mimi uses 8 quantizers with a codebook size of 2048; "
            "the frame rate is 12.5Hz and the bitrate is 1.1kbps.",
        ),
        (
            "How many parameters does Helium have, "
            "and on how many pretraining tokens was it trained?",
            "Helium is a 7B-parameter model pretrained on 2.1T tokens.",
            "Helium has 7 billion parameters and was pretrained on 2.1 trillion tokens.",
        ),
    ],
)
def test_existing_quantitative_multipart_forms_remain_supported(question, quote, text):
    plan = infer_answer_parts(question)
    assert len(plan.required) > 1
    assert assess_answer_coverage(plan, ((text, (quote,)),)).status == "complete"


def test_translation_parts_require_the_correct_table_columns_and_model():
    question = (
        "According to Table 2, what BLEU scores does Transformer (big) report "
        "for English-to-German and English-to-French?"
    )
    quotes = ("Model | EN-DE | EN-FR", "Transformer (big) | 28.4 | 41.8")
    text = "The scores are 28.4 for English-to-German and 41.8 for English-to-French."
    plan = infer_answer_parts(question)
    assert assess_answer_coverage(plan, ((text, quotes),)).status == "complete"
    swapped = "The scores are 41.8 for English-to-German and 28.4 for English-to-French."
    assert assess_answer_coverage(plan, ((swapped, quotes),)).status == "incomplete"
    assert assess_answer_coverage(plan, ((text, quotes[1:]),)).status == "incomplete"
    wrong_model = (quotes[0], "Transformer (base) | 28.4 | 41.8")
    assert assess_answer_coverage(plan, ((text, wrong_model),)).status == "incomplete"


def test_model_comparison_requires_both_rows_and_the_requested_metric():
    question = (
        "According to Table 4, what XWinograd-zh accuracies do the Transformer "
        "and H-Net (2-stage) achieve?"
    )
    header = "Model | Other metric | XWinograd-zh"
    transformer = ("Transformer achieves 0.599.", (header, "Transformer | 0.7404 | 0.599"))
    hnet = ("H-Net (2-stage) achieves 0.663.", (header, "H-Net (2-stage) | 0.7032 | 0.663"))
    plan = infer_answer_parts(question)
    assert assess_answer_coverage(plan, (transformer, hnet)).status == "complete"
    assert assess_answer_coverage(plan, (transformer, transformer)).status == "incomplete"
    wrong_column = (hnet[0], ("Model | XWinograd-zh | Other metric", hnet[1][1]))
    assert assess_answer_coverage(plan, (transformer, wrong_column)).status == "incomplete"
