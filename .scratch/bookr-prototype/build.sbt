ThisBuild / scalaVersion := "3.3.4"
ThisBuild / scalafmtOnCompile := true

lazy val root = (project in file("."))
  .settings(
    name := "bookr-prototype",
    libraryDependencies += "org.scalameta" %% "munit" % "1.3.6" % Test
  )
