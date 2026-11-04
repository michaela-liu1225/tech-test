import unittest

from techtest.models import ScalarResult, ScalarResults


class ScalarResultsEdgeCaseTests(unittest.TestCase):
    def test_empty_results_produce_no_records(self):
        self.assertEqual(list(ScalarResults()), [])

    def test_results_without_errors_include_zero(self):
        results = ScalarResults()
        results.add_result("Zero", 0.0)
        results.add_result("Positive", 42.0)

        self.assertEqual(
            list(results),
            [ScalarResult("Zero", 0.0, None), ScalarResult("Positive", 42.0, None)],
        )

    def test_errors_without_results_include_none(self):
        results = ScalarResults()
        results.add_error("Failed", "Pricing failed")
        results.add_error("NoMessage", None)

        self.assertEqual(
            list(results),
            [
                ScalarResult("Failed", None, "Pricing failed"),
                ScalarResult("NoMessage", None, None),
            ],
        )

    def test_result_and_error_combine_once_in_either_arrival_order(self):
        for error_first in (False, True):
            with self.subTest(error_first=error_first):
                results = ScalarResults()
                if error_first:
                    results.add_error("Trade", "Model warning")
                    results.add_result("Trade", 0.0)
                else:
                    results.add_result("Trade", 0.0)
                    results.add_error("Trade", "Model warning")

                self.assertEqual(list(results), [ScalarResult("Trade", 0.0, "Model warning")])

    def test_result_entries_precede_error_only_entries(self):
        results = ScalarResults()
        results.add_error("FailedFirst", "First failure")
        results.add_error("WithWarning", "Model warning")
        results.add_result("Successful", 42.0)
        results.add_result("WithWarning", 10.0)
        results.add_error("FailedLast", "Last failure")

        self.assertEqual(
            list(results),
            [
                ScalarResult("Successful", 42.0, None),
                ScalarResult("WithWarning", 10.0, "Model warning"),
                ScalarResult("FailedFirst", None, "First failure"),
                ScalarResult("FailedLast", None, "Last failure"),
            ],
        )

    def test_iterators_are_independent_and_repeatable(self):
        results = ScalarResults()
        results.add_result("Successful", 42.0)
        results.add_error("Failed", "Pricing failed")
        expected = [
            ScalarResult("Successful", 42.0, None),
            ScalarResult("Failed", None, "Pricing failed"),
        ]

        first_iterator = iter(results)
        second_iterator = iter(results)
        self.assertEqual(next(first_iterator), expected[0])
        self.assertEqual(list(second_iterator), expected)
        self.assertEqual(list(first_iterator), expected[1:])
        self.assertEqual(list(results), expected)


if __name__ == "__main__":
    unittest.main()
