using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RequestHub.Core.Data.Migrations
{
    /// <inheritdoc />
    public partial class EnforceSingleProposedRecommendation : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateIndex(
                name: "IX_Recommendations_RequestId_Proposed",
                table: "Recommendations",
                column: "RequestId",
                unique: true,
                filter: "\"Status\" = 'Proposed'");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_Recommendations_RequestId_Proposed",
                table: "Recommendations");
        }
    }
}
