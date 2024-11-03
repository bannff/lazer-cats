(ns my-clojure-app.core-test
  (:require [clojure.test :refer [deftest is testing]]
            [my-clojure-app.core :refer [greet]]))

(deftest greet-test
  (testing "greet function"
    (is (= "Hello, World!" (greet "World")))))

(deftest a-test
  (testing "Example test"
    (is (= 1 1)))) ; This should pass
